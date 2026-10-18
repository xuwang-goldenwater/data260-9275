"""Token counts per prompt section (HW6 Part 3).

Ollama reports one number for the whole prompt (prompt_eval_count). To see what
each memory type costs, every section is tokenised separately with the model's
own tokenizer (Qwen2.5, ~7 MB download from Hugging Face, no model weights).

The sections do not add up to prompt_eval_count exactly: the chat template adds
role markers (<|im_start|>system ...) around every message. That difference is
logged as "template_overhead".

If the tokenizer cannot be loaded, a rough chars/4 estimate is used and every
log row says so (tokenizer = "approx_chars_div_4").
"""
from functools import lru_cache

TOKENIZER_ID = "Qwen/Qwen2.5-3B-Instruct"     # matches CHAT_MODEL qwen2.5:3b


@lru_cache(maxsize=1)
def _tokenizer():
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(TOKENIZER_ID)
    except Exception as exc:                      # offline, or transformers missing
        print(f"[warn] tokenizer {TOKENIZER_ID} unavailable ({type(exc).__name__}); "
              "using chars/4 estimate")
        return None


def tokenizer_name() -> str:
    return TOKENIZER_ID if _tokenizer() is not None else "approx_chars_div_4"


def count(text: str) -> int:
    if not text:
        return 0
    tok = _tokenizer()
    if tok is None:
        return max(1, round(len(text) / 4))
    return len(tok.encode(text, add_special_tokens=False))
