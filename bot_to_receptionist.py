from model import llm_model
from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import AnyMessage, add_messages
from langchain_anthropic import ChatAnthropic
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import tools_condition
import shutil
import uuid
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser

llm = llm_model()


def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> dict:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )

def _print_event(event: dict, _printed: set, max_length=1500):
    current_state = event.get("dialog_state")
    if current_state:
        print("Currently in: ", current_state[-1])
    message = event.get("messages")
    if message:
        if isinstance(message, list):
            message = message[-1]
        if message.id not in _printed:
            msg_repr = message.pretty_repr(html=True)
            if len(msg_repr) > max_length:
                msg_repr = msg_repr[:max_length] + " ... (truncated)"
            print(msg_repr)
            _printed.add(message.id)


def get_pending_patient_information_data_from_db():
    from pymongo import MongoClient

    # Connect to MongoDB (Default Port: 27017)
    client = MongoClient("mongodb://localhost:27017/")

    # Create a database
    db = client["patient_db"]

    # Access the collection (table)
    patient_information_details_table_collection = db["patient_information_details_table"]

    # Create a list to store extracted data
    result_list = []

    # Filter for only documents where appointment_status is "Pending"
    query = {"appointment_status": "Pending"}

    # Loop through filtered documents and extract desired keys
    for document in patient_information_details_table_collection.find(query):
        data = {
            "username": document.get("username"),
            "hospital_name": document.get("hospital_name"),
            "location": document.get("location"),
            "specialization": document.get("specialization"),
            "appointment_booking_date": document.get("appointment_booking_date"),
            "appointment_booking_time": document.get("appointment_booking_time"),
            "appointment_status": document.get("appointment_status"),
        }
        result_list.append(data)

    return result_list


from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class Assistant:
    def __init__(self, runnable: Runnable):
        self.runnable = runnable

    def __call__(self, state: State, config: RunnableConfig):
        while True:
            configuration = config.get("configurable", {})
            passenger_id = configuration.get("patient_data", None)
            current_date = configuration.get("current_date", None)
            state = {**state, "user_info": passenger_id,"current_date": current_date}
            # print("state: ")
            # print(state)
            result = self.runnable.invoke(state)
            # If the LLM happens to return an empty response, we will re-prompt it
            # for an actual response.
            if not result.tool_calls and (
                not result.content
                or isinstance(result.content, list)
                and not result.content[0].get("text")
            ):
                messages = state["messages"] + [("user", "Respond with a real output.")]
                state = {**state, "messages": messages}
            else:
                break
        # print({"messages": result})
        return {"messages": result}
    
primary_assistant_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are Azentyk AI Doctor Assistant — a polite, professional, and friendly virtual assistant that helps hospitals schedule doctor appointments on behalf of patients. You interact directly with **hospital receptionists** to confirm, reschedule, or cancel doctor appointments.

Your role is narrowly focused on appointment coordination. You must **always follow the step-by-step flow** below.  
⚠️ Never merge two steps into a single response. Each step must be its **own separate message**, always ending with `<END_OF_TURN>`.  

---

🎯 **Primary Goal**  
Help schedule, reschedule, or cancel a doctor’s appointment for the patient by interacting with the hospital receptionist in a natural but structured voice.  

---

### ✅ **Behavior Rules**

- Do **not** ask open-ended questions like “How can I help you?”.  
- Do **not** wait for the receptionist to speak first — always start with Step 1.  
- Speak in short, polite, natural sentences (no bullet points in responses).  
- Always end a message with `<END_OF_TURN>`.  
- End the full call with `<END_OF_CALL>` and a JSON status.  

---

### 📞 **Appointment Flow (Strictly One Step per Turn)**

**Step 1 – Greeting (always first message)**  
Hello, this is Azentyk AI Doctor Assistant. I’m contacting you to help schedule an appointment for {{patientname}}. <END_OF_TURN>  

**Step 2 – Appointment Request**  
The patient {{patientname}} would like an appointment with Dr. {{doctor_name}} at {{hospital_name}}, {{location}} on {{appointment_date}} at {{appointment_time}}. Could you please confirm if that slot is available? <END_OF_TURN>  

**Step 3A. If Slot Is Available**  
- Great, thank you! I’ll update the patient with the details.  
  ```json
  {{ "appointment_status": "confirmed" }}
  ```  <END_OF_CALL>

**Step 3B. If Slot Is Unavailable**  
- Understood. Could you please provide alternative available **dates and times** for Dr. {{doctor_name}}? I’ll check with the patient and follow up. <END_OF_TURN>

---

### 🔁 **Input Validation Logic**:

- If **both date and time** are given → proceed directly.
- If **only date** is given →  
  - Example : Got it. What time would be available on that date? <END_OF_TURN>

- If **only time** is given →  
  Example : Thanks. Could you please confirm the date for that time? <END_OF_TURN>

---

**Step 4. Receptionist Shares Both Date and Time**  
- Example : Thank you. I’ve noted the options. I’ll confirm with the patient and reconnect if needed.  
  ```json
  {{ "appointment_status": "rescheduled" }}
  ```  
  <END_OF_CALL>

**Step 5. If Appointment Is Cancelled**  
- Example : Got it. I’ll update the patient accordingly.  
  ```json
  {{ "appointment_status": "cancelled" }}
  ```  
  <END_OF_CALL>

---

### ❓ **If Receptionist Asks About Appointment Details:**

Respond with full details as available:
- Example : The patient's name is Aravind. The appointment is requested at Sri Ramachandra Medical Centre, located in Chennai. <END_OF_TURN>

---

### 🚫 **If Receptionist Asks About Non-Appointment Topics:**

- Example :I'm here only to assist with doctor appointment-related matters like booking, rescheduling, or cancelling appointments. For other queries, please contact the hospital directly. <END_OF_TURN>

---

📄 **Context**:

\n\nCurrent Patient Info:\n<User>\n{user_info}\n</User>\n
\nCurrent Date:\n<Date>\n{current_date}\n</Date>\n
"""
        ),
        ("placeholder", "{messages}"),
    ]
)



from langchain_community.utilities import GoogleSerperAPIWrapper

google_search = GoogleSerperAPIWrapper(k = 4, type = "search")
from langchain.tools import tool

@tool
def google_search_hospital_details(query: str) -> str:
    """Search for hospital information including:
    - Hospital names
    - Hospital locations
    - Available specialties
    
    Use this when users ask about hospital options, specialties, etc.
    
    Use this tool only if no answer from hospital_details db"""
    docs = google_search.run(query)
    return ""


part_1_tools = [google_search_hospital_details]
part_1_assistant_runnable = primary_assistant_prompt | llm.bind_tools(part_1_tools)


from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import tools_condition

builder = StateGraph(State)


# Define nodes: these do the work
builder.add_node("assistant", Assistant(part_1_assistant_runnable))
builder.add_node("tools", create_tool_node_with_fallback(part_1_tools))
# Define edges: these determine how the control flow moves
builder.add_edge(START, "assistant")
builder.add_conditional_edges(
    "assistant",
    tools_condition,
)
builder.add_edge("tools", "assistant")

# The checkpointer lets the graph persist its state
# this is a complete memory for the entire graph.
memory = MemorySaver()
part_1_graph = builder.compile(checkpointer=memory)
