import os

from jinja2 import Environment

from src.core.config import WORK_DIR
from src.infrastructure.llms import LLMRouter
from src.domain.llm import LLMMessage


def _read_file(file):
    with open(file, "r", encoding="utf-8") as _fp:
        return _fp.read()


def _parse_template(template_str, **kwargs):
    env = Environment()
    template = env.from_string(template_str)
    return template.render(**kwargs)


class LLMRepo:
    _PROMPTS_TMP = {}
    def __init__(self, prompt_folder: str=None, router: LLMRouter=None):
        if prompt_folder is None:
            prompt_folder = os.path.join(WORK_DIR, "data", 'prompts')
        self.prompt_folder = prompt_folder
        if router is None:
            router = LLMRouter()
        self.router = router

    def get_prompt(
            self,
            task_type, *,
            system_arg: dict=None,
            user_arg: dict=None
    )-> list[LLMMessage]:
        messages = {}
        for f in os.listdir(self.prompt_folder):
            try:
                if task_type.lower() in f.lower():
                    f = os.path.join(self.prompt_folder, f)
                    if os.path.isdir(f):
                        for tmp in os.listdir(f):
                            if "sys" in tmp.lower():
                                txt = _read_file(os.path.join(f, tmp))
                                LLMRepo._PROMPTS_TMP["system_" + task_type] = txt
                                messages["system"] = _parse_template(
                                    txt, **(system_arg or {})
                                )
                            elif "user" in tmp.lower():
                                txt = _read_file(os.path.join(f, tmp))
                                LLMRepo._PROMPTS_TMP["user_" + task_type] = txt
                                messages["user"] = _parse_template(
                                    txt, **(user_arg or {})
                                )
                    else:
                        txt = _read_file(f)
                        LLMRepo._PROMPTS_TMP["system_" + task_type] = txt
                        messages["system"] = _parse_template(
                            txt, **(system_arg or {})
                        )
            except:  # noqa E722
                pass
        if not messages:
            if "user_"+task_type in LLMRepo._PROMPTS_TMP:
                txt = LLMRepo._PROMPTS_TMP["user_" + task_type]
                messages["user"] = _parse_template(
                    txt, **(user_arg or {})
                )
            elif "system_"+task_type in LLMRepo._PROMPTS_TMP:
                text = LLMRepo._PROMPTS_TMP["system_"+task_type]
                messages["system"] = _parse_template(
                    text, **(system_arg or {})
                )
        if messages:
            return [
                LLMMessage(role=k, content=messages[k])
                for k in ["system", "user"] if k in messages
            ]
        raise ValueError("No such task_type `%s` found" % (task_type,))

    async def run(
            self,
            task_type,
            messages: list[LLMMessage],
            payload: dict,
            timeout=5,
            temperature=0,
            max_tokens=1024,
            response_format=None
    ):
        return await self.router.run(
            task_type=task_type,
            messages=messages,
            payload=payload,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format
        )


