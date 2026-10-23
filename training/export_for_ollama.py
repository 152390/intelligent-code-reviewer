"""Package the trained LoRA model so the standalone application can use it through Ollama.

The executable does not contain PyTorch (it would add several gigabytes), so it talks to the
model through a local Ollama server. This script:
  1. loads the base model and your LoRA adapter, and MERGES them into one model;
  2. saves the merged model (Hugging Face format);
  3. writes a Modelfile and prints the two commands that convert it to GGUF and register it
     with Ollama under the name 'icr-reviewer'.

Run on the machine/Colab where you trained (needs requirements-train.txt):
  python training/export_for_ollama.py --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
      --adapter outputs/lora-reviewer --out outputs/merged
"""
import argparse
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", default="outputs/merged")
    ap.add_argument("--name", default="icr-reviewer")
    a = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    base = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float16)
    merged = PeftModel.from_pretrained(base, a.adapter).merge_and_unload()
    merged.save_pretrained(a.out, safe_serialization=True)
    AutoTokenizer.from_pretrained(a.model).save_pretrained(a.out)

    gguf = os.path.join(os.path.dirname(os.path.abspath(a.out)), f"{a.name}-q8_0.gguf")
    modelfile = os.path.join(os.path.dirname(os.path.abspath(a.out)), "Modelfile")
    with open(modelfile, "w") as f:
        f.write(f"FROM {gguf}\nPARAMETER temperature 0\nPARAMETER num_ctx 8192\n")
    print(f"""
Merged model saved to {a.out}

Next steps:
  1) Convert to GGUF with llama.cpp (once:  git clone https://github.com/ggerganov/llama.cpp
                                            pip install -r llama.cpp/requirements.txt)
       python llama.cpp/convert_hf_to_gguf.py {a.out} --outtype q8_0 --outfile {gguf}
  2) Copy {os.path.basename(gguf)} and Modelfile to the computer that runs the app, then:
       ollama create {a.name} -f Modelfile
  3) In ICR Reviewer choose "Local LLM server" and model name: {a.name}
""")


if __name__ == "__main__":
    main()
