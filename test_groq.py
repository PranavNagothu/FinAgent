import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

load_dotenv(override=True)
groq_api_key = os.getenv("GROQ_API_KEY")

try:
    print(f"Testing Groq API with key formatting: {groq_api_key[:8]}...")
    groq_llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=groq_api_key, temperature=0.0)
    res = groq_llm.invoke([HumanMessage(content="Hello! Are you working?")])
    print(f"Groq Output: {res.content}")
except Exception as e:
    print(f"Groq Test Failed: {e}")
