from openai import OpenAI


def create_dashscope_client(
    api_key: str,
    base_url: str | None = None,
) -> OpenAI:
    """Create an OpenAI-compatible client pointed at DashScope (阿里云百炼).

    Args:
        api_key: DashScope API key (from config.vision.dashscope_api_key).
        base_url: Override for non-standard endpoints.
                  Default: 国内北京站.

    Returns:
        OpenAI client for chat.completions.create() with qwen3-vl-* models.
    """
    return OpenAI(
        api_key=api_key,
        base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
