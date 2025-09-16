from langchain_chroma import Chroma
from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain.retrievers.document_compressors import LLMChainFilter
from langchain_community.retrievers import BM25Retriever
from langchain_openai import AzureOpenAIEmbeddings
from model import llm_model
import os

llm = llm_model()

# # Load Azure OpenAI embedding environment
# embedding_deployment_name = os.environ["embedding_deployment_name"]
# embedding_api_version = os.environ["embedding_api_version"]
# embedding_azure_endpoint = os.environ["embedding_azure_endpoint"]
# embedding_api_key = os.environ["embedding_api_key"]

def retriever_model():

    # Initialize embeddings
    embeddings = AzureOpenAIEmbeddings(
        model="text-embedding-3-small",
        azure_deployment="call-automation-openai-text-embedding-3-small",
        api_version="2023-05-15",
        azure_endpoint="https://call-automation-openai.openai.azure.com/",
        api_key="FsUF4JAg0SbHFchYIFNjxIEUPOmnt9i5uA6UMcf49TrPk7qFbrphJQQJ99BDACYeBjFXJ3w3AAABACOGX1Nm",
    )

    # Load vector DB retriever
    db = Chroma(
        persist_directory="./doctor_details_db",
        embedding_function=embeddings
    )

    retriever = db.as_retriever(search_kwargs={'k':20})
    # compressor = LLMChainExtractor.from_llm(llm) # _filter = LLMChainFilter.from_llm(llm)
    # compression_retriever = ContextualCompressionRetriever(base_compressor=_filter, base_retriever=retriever)

    return retriever
