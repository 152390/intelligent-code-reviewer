"""LoRA fine-tuning of an open-weight code LLM (Section 3.4.3; Hu et al., 2021).

One adapter is trained on BOTH behaviours at once (multi-task): writing review
comments and labelling changed blocks as faulty/clean with a category. The two
tasks are mixed in train.jsonl and distinguished by their TASK line in the prompt.

Only the assistant's answer contributes to the loss (prompt tokens are masked with
-100), so the model learns to produce the answer, not to repeat the prompt.

Runs on a free Google Colab T4 (16 GB) with --load-4bit (QLoRA style).

Usage
  python training/train_lora.py --train data/processed/train.jsonl --val data/processed/val.jsonl \
      --model Qwen/Qwen2.5-Coder-1.5B-Instruct --out outputs/lora-reviewer --load-4bit
"""
from __future__ import annotations
import argparse
import json
import os
import random


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    ap.add_argument("--out", default="outputs/lora-reviewer")
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    import numpy as np
    import torch
    from datasets import load_dataset
    from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq,
                              Trainer, TrainingArguments, set_seed)
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    random.seed(a.seed)
    np.random.seed(a.seed)
    set_seed(a.seed)

    tok = AutoTokenizer.from_pretrained(a.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    kwargs = {"torch_dtype": torch.float16}
    if a.load_4bit:
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(a.model, device_map="auto", **kwargs)
    if a.load_4bit:
        model = prepare_model_for_kbit_training(model)

    # LoRA: freeze the base model, add small trainable low-rank matrices to the attention layers.
    lora = LoraConfig(r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=a.lora_dropout, bias="none",
                      task_type="CAUSAL_LM", target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()          # report this number in Chapter Four

    def tokenize(ex):
        prompt = tok.apply_chat_template(ex["messages"][:-1], tokenize=False, add_generation_prompt=True)
        answer = ex["messages"][-1]["content"] + tok.eos_token
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(answer, add_special_tokens=False)["input_ids"]
        if len(p_ids) + len(a_ids) > a.max_len:        # too long: keep the answer, cut the prompt's start
            p_ids = p_ids[-(a.max_len - len(a_ids)):] if len(a_ids) < a.max_len else []
            a_ids = a_ids[:a.max_len - len(p_ids)]
        ids = p_ids + a_ids
        return {"input_ids": ids, "attention_mask": [1] * len(ids),
                "labels": [-100] * len(p_ids) + a_ids}

    ds = load_dataset("json", data_files={"train": a.train, "val": a.val})
    ds = ds.map(tokenize, remove_columns=ds["train"].column_names)

    args = TrainingArguments(
        output_dir=a.out, num_train_epochs=a.epochs, learning_rate=a.lr,
        per_device_train_batch_size=a.batch, per_device_eval_batch_size=a.batch,
        gradient_accumulation_steps=a.grad_accum, warmup_ratio=0.03, lr_scheduler_type="cosine",
        logging_steps=20, eval_strategy="steps", eval_steps=200, save_steps=200, save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model="eval_loss", fp16=True,
        gradient_checkpointing=True, report_to="none", seed=a.seed)
    trainer = Trainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["val"],
                      data_collator=DataCollatorForSeq2Seq(tok, label_pad_token_id=-100, padding=True))
    trainer.train()
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)

    # Record everything needed to reproduce the run (Section 3.7).
    import transformers, peft
    with open(os.path.join(a.out, "run_info.json"), "w") as f:
        json.dump({"args": vars(a), "torch": torch.__version__, "transformers": transformers.__version__,
                   "peft": peft.__version__, "final_eval": trainer.evaluate(),
                   "log_history": trainer.state.log_history}, f, indent=2)
    print(f"Adapter saved to {a.out}")


if __name__ == "__main__":
    main()
