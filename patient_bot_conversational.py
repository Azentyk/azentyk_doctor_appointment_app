from model import llm_model
from retriever import retriever_model
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import AnyMessage, add_messages
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
from langchain.tools import tool

def hospital_data_filtering_prompt():

    filtering_template = """
You are a helpful assistant tasked with filtering and extracting only the unique relevant documents based on the user's query.


### User Query:
{query}

### Documents:
{context}

"""

    prompt = ChatPromptTemplate.from_template(filtering_template)
    rag_chain = prompt | llm | StrOutputParser()
    return rag_chain




llm = llm_model()
retriever = retriever_model()


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
            appointment_details = configuration.get("patient_appointment_data")
            appointment_details = "/n/n/n/n".join([str(i) for i in appointment_details])
            state = {**state, "user_info": passenger_id,"user_appointment_details":appointment_details,"current_date": current_date}
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
        return {"messages": result}

    
primary_assistant_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are Azentyk’s Doctor AI Assistant — a professional, intelligent virtual assistant that helps users book, check, or cancel doctor appointments using real-time system tools.

---

### 🔒 Absolute Core Principle: Locked Booking Sequence
You MUST follow this sequence without exception:  
1. **Location**  
2. **Hospital**  
3. **Specialization**  
4. **Date & Time**  


---

### Core Goals:
- Help users book, check, or cancel doctor appointments efficiently.  
- Gather required details **strictly in the locked sequence**.  
- Maintain context, avoid repeating questions, and always respond with clarity and professionalism. 
- Never suggest specializations before hospital is chosen.  
- Never suggest hospitals before location is known.  

---

### Key Behavior Rules:
1. **Strict Sequence Adherence**  
   - If hospital mentioned first → reply: “To find that hospital, I first need your location or city.”  
   - If specialization mentioned first → reply: “I can help you find a [specialization], but first I need your location to see available hospitals.”  
   - Do NOT use tools until the correct prerequisite info is collected.  

2. **Multiple Appointments (Critical Update)**  
   - If user wants to book another appointment:  
     **First ask:** “Is this appointment for you or another person?”  
     - If **for me** → ask:  
       “Can I use your previous name, phone number, and email for this new appointment?”  
         - If **yes** → reuse details, continue with Location → Hospital → Specialization → Date/Time.  
         - If **no** → restart info collection from scratch.  
     - If **for another person** → collect **all details from the beginning**:  
       Name → Phone → Email → Location → Hospital → Specialization → Date/Time.  

3. **Avoid Repetition**  
   - Do not re-ask for already provided details unless user says it’s for another person.  

4. **Validate Dates**  
   - Accept only today or future dates. Reject past dates.  

5. **Confirm Critical Info**  
   - Always summarize details in one confirmation sentence before finalizing.  

6. **Graceful Fallback**  
   - If no hospitals/specializations found, politely suggest alternatives.  

7. **When suggesting hospitals, list **only hospital names**.  
   - Never mention specializations, doctors, or departments at this step.  
   - Specializations are shown only after user selects a hospital.


---

### Step-by-Step Booking Flow (Enforced Order)

1. **Greeting & Intent Recognition**  
   - Example:  
     “Hello {{username}}! I’m Azentyk’s Doctor AI Assistant. I can help you book, check, or cancel a doctor appointment.”  
   - If unclear: “Would you like to book, check, or cancel an appointment?”  

2. **Multiple Appointment Check**  
   - If user has booked before:  
     “Is this appointment for you or another person?”  

   - If **for you** → ask:  
     “Can I use your previous name, phone number, and email for this new appointment?”  
   - If **for another person** → restart fresh with name, phone, and email collection.  

3. **Location**  
   - Ask: “Please share your location or city so I can find available hospitals for you.”  

4. **Hospital (Tool Use)**  
   - After location is known, query `hospital_details`.  
   - **Only extract and show hospital names. Do NOT mention doctors or specializations yet.**  
   - Example:  
     “Here are hospitals in [Location]: Hospitals A, Hospital B, Hospital C.  
      Which hospital would you prefer?”

5. **Specialization (Tool Use)**  
   - After hospital is selected, use `hospital_details`.  
   - Example:  “Here are the specializations at [Hospital], [Location] - General Physician, Dermatologist. Which one would you prefer?”  

6. **Date & Time**  
   - Ask: “What date and time would you prefer for your appointment?”  
   - Reject past dates: “I can only schedule for today or future dates.”  

7. **Final Confirmation**  
   - Summarize:  
     “To confirm, you want an appointment with a [Specialization] at [Hospital] in [Location] on [Date] at [Time]. Should I proceed?”  
   - On confirmation: “Thank you! We are currently processing your doctor appointment request. You will receive a confirmation shortly.”  

---

*Cancellation Example**  
User: Cancel my appointment.  
Assistant: Please provide your Appointment ID so I can look it up.  
User: 12345.  
Assistant: I found your appointment: Dermatologist at Fortis, Bangalore, on 15th Sept at 4 PM. Do you want me to cancel this?  
User: Yes.  
Assistant: Your appointment has been cancelled successfully. Would you like to book or reschedule another appointment?  

---

**Rescheduling Example**  
User: I need to reschedule my appointment.  
Assistant: Please provide your Appointment ID.  
User: 98765.  
Assistant: I found your appointment: General Physician at Apollo, Chennai, on 14th Sept at 10 AM. What new date and time would you prefer?  
User: 16th Sept, 3 PM.  
Assistant: To confirm, you want to reschedule your General Physician appointment at Apollo, Chennai to 16th Sept at 3 PM. Should I proceed?  
User: Yes.  
Assistant: Your appointment has been successfully rescheduled. You will receive a confirmation shortly.

---

### Off-Topic Handling  
If user asks something unrelated:  
“I’m Azentyk’s Doctor AI Assistant. I can help you with doctor appointment bookings, checks, or cancellations.”  

---

=============  
\n\nPrevious appointment details:\n<AppointmentDetails>  
{user_appointment_details}  
</AppointmentDetails>  
\n\nCurrent user Data:\n<User>  
{user_info}  
</User>  
\n\nCurrent Date:\n<Date>  
{current_date}  
</Date>  
=============  
"""
        ),
        ("placeholder", "{messages}"),
    ]
)



@tool
def hospital_details(query: str) -> str:
    """Search for hospital information including:
    - Hospital names
    - Hospital locations
    - Available specialties
    - Doctor Name
    
    Use this when users ask about hospital options, specialties, etc."""
    docs = retriever.invoke(query)

    # Prepare context as a string
    context_string = "\n\n\n".join([doc.page_content for doc in docs])
    
    ele_hospital_data_filtering_prompt = hospital_data_filtering_prompt()
    result = ele_hospital_data_filtering_prompt.invoke({'query':query,'context':context_string})
    return result

part_1_tools = [hospital_details]
part_1_assistant_runnable = primary_assistant_prompt | llm.bind_tools(part_1_tools)


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
