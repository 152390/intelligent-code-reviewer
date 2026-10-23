"""Model backends for the comment generator, error detector and explanation generator.

Three interchangeable backends share one method, generate(prompt) -> str:

  hf         Open-weight code LLM loaded with Hugging Face transformers, optionally
             with the LoRA adapter you train in training/train_lora.py. THIS IS THE
             RESEARCH CONFIGURATION (Section 3.4.3).
  openai     Any OpenAI-compatible server running an open-weight model locally:
             Ollama (default URL), vLLM, llama.cpp server, LM Studio. Useful on a
             laptop without a big GPU, e.g. `ollama pull qwen2.5-coder:7b`.
  heuristic  An OFFLINE STUB made of hand-written pattern rules. It exists only so the
             pipeline (ingestion, context, static analysis, filter, explanation, output)
             can be demonstrated and tested without a model. It is NOT the research
             model and its results must not be reported as such.
"""
from __future__ import annotations
import json
import os
import re
from .prompts import SYSTEM


def extract_json(text: str):
    """LLMs sometimes wrap JSON in prose or ``` fences; pull out the first JSON value."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
    return None


class HFBackend:
    last_confidence: float | None = None

    def __init__(self, model: str, adapter: str | None = None, load_4bit: bool = False,
                 max_new_tokens: int = 512):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        kwargs = {"torch_dtype": torch.float16 if torch.cuda.is_available() else torch.float32}
        if load_4bit:
            from transformers import BitsAndBytesConfig
            kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True,
                                                               bnb_4bit_compute_dtype=torch.float16)
        self.tok = AutoTokenizer.from_pretrained(model)
        self.model = AutoModelForCausalLM.from_pretrained(model, device_map="auto", **kwargs)
        if adapter:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, adapter)
        self.model.eval()
        self.max_new_tokens = max_new_tokens
        self.name = f"hf:{model}" + (f"+lora:{adapter}" if adapter else "")

    def generate(self, prompt: str, system: str = SYSTEM) -> str:
        import torch
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True,
                                           return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(ids, max_new_tokens=self.max_new_tokens, do_sample=False,
                                      pad_token_id=self.tok.eos_token_id,
                                      output_scores=True, return_dict_in_generate=True)
        gen = out.sequences[0][ids.shape[1]:]
        # Model confidence = average probability the model gave to the tokens it produced.
        # This comes from the model's own probabilities, not from a number it writes,
        # which is better calibrated than asking it to grade itself.
        probs = [torch.softmax(sc[0].float(), -1)[tok].item() for sc, tok in zip(out.scores, gen)]
        self.last_confidence = float(sum(probs) / len(probs)) if probs else 0.5
        return self.tok.decode(gen, skip_special_tokens=True)


class OpenAICompatBackend:
    def __init__(self, model: str, base_url: str | None = None, max_tokens: int = 700):
        self.model = model
        self.base_url = (base_url or os.environ.get("ICR_LLM_URL", "http://localhost:11434/v1")).rstrip("/")
        self.api_key = os.environ.get("ICR_LLM_KEY", "none")
        self.max_tokens = max_tokens
        self.name = f"openai-compat:{model}@{self.base_url}"

    def generate(self, prompt: str, system: str = SYSTEM) -> str:
        import requests
        try:
            r = requests.post(f"{self.base_url}/chat/completions", timeout=600,
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              json={"model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
                                    "messages": [{"role": "system", "content": system},
                                                 {"role": "user", "content": prompt}]})
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Cannot reach the LLM server at {self.base_url}. Start Ollama (or LM Studio's "
                               "local server) first, check the Server URL, or choose the Demo stub backend.")
        except requests.exceptions.Timeout:
            raise RuntimeError("The LLM server took longer than 10 minutes to answer. Try a smaller model.")
        if r.status_code == 404:
            raise RuntimeError(f"The server does not have the model '{self.model}'. With Ollama run: "
                               f"ollama pull {self.model}   (or use 'Test connection' to list available models)")
        if r.status_code >= 400:
            raise RuntimeError(f"The LLM server returned error {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- offline stub
# (pattern, category, message template, confidence, suggestion). {0} = first regex group.
DETECTOR_RULES = [
    (r"range\(\s*len\(([\w.]+)\)\s*\+\s*1\s*\)", "logic",
     "Loop runs one step past the end of `{0}`; the last iteration indexes out of range.", 0.80,
     "Iterate with range(len({0})) or loop over the items directly."),
    (r"\.execute\(\s*f[\"']|\.execute\([^)]*%\s|\.execute\([^)]*\+|executeQuery\([^)]*\+", "security",
     "SQL query is built from a formatted string, so input can inject SQL.", 0.85,
     "Use parameterised queries (placeholders) and pass values separately."),
    (r"\beval\(|\bexec\(", "security",
     "eval/exec runs arbitrary code if its argument comes from a user.", 0.85,
     "Parse the input explicitly (e.g. ast.literal_eval or a small parser) instead of eval."),
    (r"def \w+\([^)]*=\s*(\[\]|\{\})", "logic",
     "Mutable default argument `{0}` is shared between calls, so state leaks across calls.", 0.70,
     "Default to None and create a new list/dict inside the function."),
    (r"(?i)(password|secret|api_key|apikey|token)\s*=\s*[\"'][^\"']{6,}[\"']", "security",
     "Credential `{0}` is hard-coded in source code.", 0.70,
     "Load secrets from environment variables or a secrets manager."),
    (r"/\s*len\(([\w.]+)\)", "logic",
     "Division by len({0}) raises ZeroDivisionError when `{0}` is empty.", 0.55,
     "Guard the empty case before dividing."),
    (r"^\s*except\s*:", "quality",
     "Bare `except:` also catches KeyboardInterrupt/SystemExit and hides real errors.", 0.60,
     "Catch the specific exception type you expect."),
    (r"(==|!=)\s*None\b", "quality",
     "Comparison to None should use `is`/`is not`.", 0.45,
     "Write `x is None` / `x is not None`."),
    (r"shell\s*=\s*True", "security",
     "subprocess with shell=True allows command injection.", 0.75,
     "Pass the command as a list and keep shell=False."),
    (r"(\w+)\s*==\s*\"", "logic",
     "String `{0}` is compared with == (reference comparison in Java).", 0.65,
     "Use {0}.equals(...) for Java strings."),
]
COMMENTER_RULES = [
    (r"^\s*print\(", "Consider using the `logging` module instead of print for diagnostics.", 0.45,
     "Replace print with logger.debug/info."),
    (r"[^\w.]\d+\.\d{2,}\b", "Magic number; consider a named constant so the intent is clear.", 0.30,
     "Define a named constant."),
    (r"#\s*TODO", "Unresolved TODO in new code; track it in an issue or resolve before merging.", 0.40,
     "Open an issue or resolve it."),
    (r"^\s*def (\w+)\(", "Function `{0}` has no docstring describing its behaviour.", 0.30,
     "Add a short docstring."),
]
CTX_RETURNS_NONE = re.compile(r"def (\w+)\([^)]*\):(?:(?!\ndef ).)*?return None", re.S)


class HeuristicBackend:
    name = "heuristic-stub (NOT the research model)"

    @staticmethod
    def _section(prompt: str, title: str) -> str:
        m = re.search(rf"### {title}[^\n]*\n(.*?)(?=\n### |\Z)", prompt, re.S)
        return m.group(1) if m else ""

    def generate(self, prompt: str, system: str = SYSTEM) -> str:
        task = re.search(r"TASK: (\w+)", prompt).group(1)
        if task == "EXPLAIN_FINDING":
            return json.dumps(self._explain(prompt))
        lines = re.findall(r"^L(\d+): (.*)$", self._section(prompt, "CHANGED CODE"), re.M)
        context = self._section(prompt, "REPOSITORY CONTEXT")
        out = []
        if task == "DETECT_ERRORS":
            for n, text in lines:
                for pat, cat, msg, conf, _ in DETECTOR_RULES:
                    m = re.search(pat, text)
                    if m:
                        out.append({"line": int(n), "category": cat, "confidence": conf,
                                    "message": msg.format(*(m.groups() or ("value",)))})
                # Context-dependent rule: only fires when the context builder retrieved
                # the callee's definition. This demonstrates the 'without context' ablation.
                for fn in CTX_RETURNS_NONE.findall(context):
                    if re.search(rf"(\+=|[-+*/])\s*{fn}\(|{fn}\([^)]*\)\s*[-+*/]", text):
                        out.append({"line": int(n), "category": "logic", "confidence": 0.75,
                                    "message": f"`{fn}()` can return None (see its definition), so this "
                                               f"arithmetic raises TypeError for unknown inputs."})
            return json.dumps({"label": "faulty" if out else "clean", "findings": out})
        for k, (n, text) in enumerate(lines):                      # REVIEW_COMMENTS
            nxt = lines[k + 1][1].strip() if k + 1 < len(lines) else ""
            for pat, msg, conf, _ in COMMENTER_RULES:
                m = re.search(pat, text)
                if m and not ("docstring" in msg and nxt.startswith(('"""', "'''"))):
                    out.append({"line": int(n), "comment": msg.format(*(m.groups() or ("",))),
                                "confidence": conf})
        return json.dumps({"comments": out})

    @staticmethod
    def _explain(prompt: str) -> dict:
        finding = re.search(r"FINDING: (.*)", prompt).group(1)
        code = (re.search(r"CODE: (.*)", prompt) or [None, ""])[1]
        evidence = [e for e in re.findall(r"^- (.*)$", prompt.split("SUPPORTING EVIDENCE:")[-1], re.M)
                    if not e.startswith(("retrieved", "none"))]      # static-analyser evidence only
        suggestion = "Review this line and adjust it to the project's conventions."
        for pat, *_rest in DETECTOR_RULES + COMMENTER_RULES:
            m = re.search(pat, code)
            if m:
                suggestion = _rest[-1].format(*(m.groups() or ("value",)))
                break
        if "return None" in finding or "can return None" in finding:
            suggestion = "Handle the None case (default price, raise a clear error, or skip the item)."
        return {"problem": finding,
                "evidence": f"The line `{code}`" + (f"; also flagged by {evidence[0]}" if evidence else ""),
                "why_it_matters": {"security": "It can be exploited by an attacker.",
                                   "logic": "The code can crash or produce wrong results at runtime."}
                .get(re.search(r"CATEGORY: (\w+)", prompt).group(1),
                     "It makes the code harder to maintain and can hide bugs."),
                "suggestion": suggestion}


def test_server(base_url: str, api_key: str | None = None) -> list[str]:
    """Check that an OpenAI-compatible server (Ollama, LM Studio, vLLM) is reachable and
    return the names of the models it offers."""
    import requests
    r = requests.get(f"{base_url.rstrip('/')}/models", timeout=10,
                     headers={"Authorization": f"Bearer {api_key or 'none'}"})
    r.raise_for_status()
    return [m.get("id", "?") for m in r.json().get("data", [])]


def make_backend(kind: str, model: str | None = None, adapter: str | None = None,
                 base_url: str | None = None, load_4bit: bool = False):
    if kind == "hf":
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            raise RuntimeError("The 'hf' backend needs PyTorch and transformers, which are not part of the "
                               "standalone executable. Use the 'openai' backend with Ollama or LM Studio, "
                               "or run from source after: pip install -r requirements-train.txt")
        return HFBackend(model or "Qwen/Qwen2.5-Coder-1.5B-Instruct", adapter, load_4bit)
    if kind == "openai":
        return OpenAICompatBackend(model or "qwen2.5-coder:7b", base_url)
    if kind == "heuristic":
        return HeuristicBackend()
    raise ValueError(f"unknown backend {kind}")
