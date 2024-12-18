import json
import os
import time  # type: ignore
from enum import Enum
from typing import Any, Callable, Union

import httpx

from litellm.litellm_core_utils.prompt_templates.factory import (
    custom_prompt,
    prompt_factory,
)
from litellm.utils import ModelResponse, Usage

llm = None


class VLLMError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        self.request = httpx.Request(method="POST", url="http://0.0.0.0:8000")
        self.response = httpx.Response(status_code=status_code, request=self.request)
        super().__init__(
            self.message
        )  # Call the base class constructor with the parameters it needs


# check if vllm is installed
def validate_environment(model: str, optional_params: Union[dict, None]):
    global llm
    try:
        from vllm import LLM, SamplingParams # type: ignore
        
        default_params = {
            "tokenizer": None,
            "tokenizer_mode": "auto",
            "skip_tokenizer_init": False,
            "trust_remote_code": False,
            "dtype": "auto",
            "quantization": None,
            "gpu_memory_utilization": 0.9,
            "load_format": "auto",
        }
        
        if optional_params is None:
            optional_params = {}
        
        params = {**default_params, **{k: v for k, v in optional_params.items() if k in default_params}}            
        optional_params = {k: v for k, v in optional_params.items() if k not in default_params}

        if llm is None:
            llm = LLM(model=model, **params)
        return llm, SamplingParams, optional_params
    except Exception as e:
        raise VLLMError(status_code=0, message=str(e))


def completion(
    model: str,
    messages: list,
    model_response: ModelResponse,
    print_verbose: Callable,
    encoding,
    logging_obj,
    optional_params: dict,
    custom_prompt_dict={},
    litellm_params=None,
    logger_fn=None,
):
    global llm
    try:
        llm, SamplingParams, optional_params = validate_environment(model=model, optional_params=optional_params)
    except Exception as e:
        raise VLLMError(status_code=0, message=str(e))
    sampling_params = SamplingParams(**optional_params)
    if model in custom_prompt_dict:
        # check if the model has a registered custom prompt
        model_prompt_details = custom_prompt_dict[model]
        prompt = custom_prompt(
            role_dict=model_prompt_details["roles"],
            initial_prompt_value=model_prompt_details["initial_prompt_value"],
            final_prompt_value=model_prompt_details["final_prompt_value"],
            messages=messages,
        )
    else:
        prompt = prompt_factory(model=model, messages=messages)

    ## LOGGING
    logging_obj.pre_call(
        input=prompt,
        api_key="",
        additional_args={"complete_input_dict": sampling_params},
    )

    if llm:
        outputs = llm.generate(prompt, sampling_params)
    else:
        raise VLLMError(
            status_code=0, message="Need to pass in a model name to initialize vllm"
        )

    ## COMPLETION CALL
    if "stream" in optional_params and optional_params["stream"] is True:
        return iter(outputs)
    else:
        ## LOGGING
        logging_obj.post_call(
            input=prompt,
            api_key="",
            original_response=outputs,
            additional_args={"complete_input_dict": sampling_params},
        )
        print_verbose(f"raw model_response: {outputs}")
        ## RESPONSE OBJECT
        model_response.choices[0].message.content = outputs[0].outputs[0].text  # type: ignore

        ## CALCULATING USAGE
        prompt_tokens = len(outputs[0].prompt_token_ids)
        completion_tokens = len(outputs[0].outputs[0].token_ids)

        model_response.created = int(time.time())
        model_response.model = model
        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        setattr(model_response, "usage", usage)
        return model_response


def batch_completions(
    model: str, messages: list, optional_params=None, custom_prompt_dict={}
):
    """
    Example usage:
    import litellm
    import os
    from litellm import batch_completion


    responses = batch_completion(
        model="vllm/facebook/opt-125m",
        messages = [
            [
                {
                    "role": "user",
                    "content": "good morning? "
                }
            ],
            [
                {
                    "role": "user",
                    "content": "what's the time? "
                }
            ]
        ]
    )
    """
    try:
        llm, SamplingParams, optional_params = validate_environment(model=model, optional_params=optional_params)
    except Exception as e:
        error_str = str(e)
        raise VLLMError(status_code=0, message=error_str)
    sampling_params = SamplingParams(**optional_params)
    prompts = []
    if model in custom_prompt_dict:
        # check if the model has a registered custom prompt
        model_prompt_details = custom_prompt_dict[model]
        for message in messages:
            prompt = custom_prompt(
                role_dict=model_prompt_details["roles"],
                initial_prompt_value=model_prompt_details["initial_prompt_value"],
                final_prompt_value=model_prompt_details["final_prompt_value"],
                messages=message,
            )
            prompts.append(prompt)
    else:
        for message in messages:
            prompt = prompt_factory(model=model, messages=message)
            prompts.append(prompt)

    if llm:
        outputs = llm.generate(prompts, sampling_params)
    else:
        raise VLLMError(
            status_code=0, message="Need to pass in a model name to initialize vllm"
        )

    final_outputs = []
    for output in outputs:
        model_response = ModelResponse()
        ## RESPONSE OBJECT
        model_response.choices[0].message.content = output.outputs[0].text  # type: ignore

        ## CALCULATING USAGE
        prompt_tokens = len(output.prompt_token_ids)
        completion_tokens = len(output.outputs[0].token_ids)

        model_response.created = int(time.time())
        model_response.model = model
        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        setattr(model_response, "usage", usage)
        final_outputs.append(model_response)
    return final_outputs


def embedding():
    # logic for parsing in - calling - parsing out model embedding calls
    pass
