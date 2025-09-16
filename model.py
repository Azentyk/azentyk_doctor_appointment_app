from dotenv import load_dotenv
import os
from langchain_openai import AzureChatOpenAI

# Load environment variables
# load_dotenv()

# # Get configuration values
# LLM_DEPLOYMENT_NAME = os.getenv("llm_deployment_name")
# LLM_API_VERSION = os.getenv("llm_api_version")
# LLM_AZURE_ENDPOINT = os.getenv("llm_azure_endpoint")
# LLM_API_KEY = os.getenv("llm_api_key")
# LLM_MODEL = os.getenv("llm_model")  # keep for info if needed
# LLM_MODEL_VERSION = os.getenv("llm_model_version")

def llm_model() -> AzureChatOpenAI:
    """
    Create and return an AzureChatOpenAI LLM instance.
    """
    return AzureChatOpenAI(
        deployment_name="call-automation-openai-gpt-4o-mini",
        temperature=0.1,  # could also load from env if needed
        api_version="2025-01-01-preview",
        azure_endpoint="https://call-automation-openai.openai.azure.com/",
        api_key="FsUF4JAg0SbHFchYIFNjxIEUPOmnt9i5uA6UMcf49TrPk7qFbrphJQQJ99BDACYeBjFXJ3w3AAABACOGX1Nm",
    )
