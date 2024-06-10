import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import nest_asyncio
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.core import VectorStoreIndex
from llama_index.core.objects import ObjectIndex
from llama_index.core.agent import FunctionCallingAgentWorker, AgentRunner
from langchain.tools import Tool
from langchain_community.tools import DuckDuckGoSearchRun

from fastapi import FastAPI, UploadFile, File
import socketio
import uvicorn

# Setup
sys.path.append('/home/mubarek/all_about_programing/Tenacious/TEAM-MATE/team-mate')

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Apply nest_asyncio
nest_asyncio.apply()

# Function to get OpenAI API key
def get_openai_api_key():
    return os.getenv('OPENAI_API_KEY')

OPENAI_API_KEY = get_openai_api_key()

# Directory containing files
directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'files')
directory = os.path.normpath(directory)

# Get all files in the directory
files = os.listdir(directory)
papers = [os.path.join(directory, file) for file in files]

print(papers)

def get_openai_client():
    """Get OpenAI client with API key."""
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("Missing OpenAI API key")
    return OpenAI(api_key=api_key)

# Get document tools
from scripts.utils import get_doc_tools

paper_to_tools_dict = {}
for paper in papers:
    print(f"Getting tools for paper: {paper}")
    name = Path(paper).stem.replace(' ', '_').replace('.pdf', '')
    vector_tool, summary_tool = get_doc_tools(paper, name)    
    paper_to_tools_dict[paper] = [vector_tool, summary_tool]

all_tools = [t for paper in papers for t in paper_to_tools_dict[paper]]

# Initialize LlamaIndex OpenAI
llm = LlamaOpenAI(model="gpt-3.5-turbo")

# Create ObjectIndex
obj_index = ObjectIndex.from_objects(
    all_tools,
    index_cls=VectorStoreIndex,
)
obj_retriever = obj_index.as_retriever(similarity_top_k=3)

# Initialize FunctionCallingAgentWorker
agent_worker = FunctionCallingAgentWorker.from_tools(
    tool_retriever=obj_retriever,
    llm=llm, 
    system_prompt=""" \
You are an agent designed to answer queries over a set of given documents.
Please always use the tools provided to answer a question. and give analysis based on your knowledge and the documents\
""",
    verbose=True
)

# Initialize AgentRunner
agent = AgentRunner(agent_worker)

# Initialize DuckDuckGoSearch tool
search = DuckDuckGoSearchRun()
duckduckgo_tool = Tool(
    name='DuckDuckGoSearch',
    func=search.run,
    description='Use this tool to perform an internet search if document retrieval does not provide sufficient information.'
)


def is_insufficient_response(response):
    """Check if the response contains phrases indicating insufficiency."""
    insufficient_phrases = [
        "is not a term or concept mentioned",
        "not found in the document",
        "not mentioned in the provided document",
        "lack of existing context",
        "does not contain"
    ]
    for phrase in insufficient_phrases:
        if phrase in response.lower():
            return True
    return False

def query_with_fallback(agent, question):
    # First, use the agent to retrieve information from documents
    response = agent.query(question)
    
    # Extract content from the response object
    content = getattr(response, 'response', None)
    
    # Debugging: print the structure of the response and content
    print(f"Response from agent: {response}")
    print(f"Extracted Content: {content}")
    
    # Check if the content is non-empty and has meaningful information
    if content and content.strip():
        # Check for specific phrases indicating insufficient response
        if is_insufficient_response(content):
            print("Detected insufficient response based on content analysis. Falling back to web search.")
            web_response = search.run(question)
            return web_response
        
        # Construct sufficiency check prompt
        sufficiency_check_prompt = f"""
        Question: {question}
        Response: {content}

        Is the above response sufficient and relevant to answer the question? Please answer with 'yes' or 'no' and provide a brief justification.
        """
        
        # Debugging: print the sufficiency check prompt
        print("Sufficiency Check Prompt:")
        print(sufficiency_check_prompt)
        
        try:
            # Perform the sufficiency check using OpenAI API
            client = get_openai_client()
            chat_completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an AI designed to assess the sufficiency and relevance of responses."},
                    {"role": "user", "content": sufficiency_check_prompt}
                ]
            )
            
            sufficiency_check = chat_completion.choices[0].message.content.strip()
            
            # Debugging: print the sufficiency check result
            print("Sufficiency Check Result:")
            print(sufficiency_check)

            # Determine if the response is sufficient based on the sufficiency check
            if 'yes' in sufficiency_check.lower():
                return content
            else:
                print("Response deemed insufficient. Falling back to web search.")
                web_response = search.run(question)
                return web_response
        except Exception as e:
            logging.error(f"Failed to get chat completion: {e}")
            return "An error occurred while trying to assess the sufficiency of the response."
    else:
        print("Document retrieval did not provide sufficient context. Falling back to web search.")
        web_response = search.run(question)
        return web_response

# Main function for testing
if __name__ == "__main__":
    response = query_with_fallback(agent, "What is Tenacious Talent - GenAI UpSkilling GEN-AI Challenge?")
    print("\nFinal Response:", response)