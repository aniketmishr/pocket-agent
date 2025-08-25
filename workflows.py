from portia import PlanBuilderV2, StepOutput, Input, PlanV2
from pydantic import BaseModel
from typing import List
class WorkFlow(BaseModel): 
    plan: PlanV2
    description: str
    args: List[str] | None = None

workflow_1 = WorkFlow(
    plan = (
            PlanBuilderV2("Fetch trending news, create a concise summary of the news")
            .single_tool_agent_step(
                step_name="search_news",
                tool = 'portia:tavily::search', 
                task = "search the current trending news",
            )
            .llm_step(
                task = """Summarize in simple the raw news data into a structured format:
                
                For each news article, provide:
                - Headline: Clear, engaging title
                - Summary: Concise 1-2 line summary of the key points
                - Link: URL to the full article
                
                Format as a clean, readable list.
                REPLY IN PLAIN TEXT
                """,
                inputs=[StepOutput("search_news")],
                step_name="news_summary"
            )
            .build()
            ),
    
    description= "Fetches current trending news, and report's the summary ", 
    args = None
)

workflow_2 = WorkFlow(
    plan = (PlanBuilderV2("Email the current weather report of a city")
    .input(name = "city")
    .input(name="email_address")
    .single_tool_agent_step(
        step_name="weather_report",
        tool = 'portia:tavily::search', 
        task = "Summarise today's weather report of a city, in a friendly and humourous manner",
        inputs=[Input('city')]
    )
    .single_tool_agent_step(
        tool = 'portia:google:gmail:send_email', 
        task = "mail the weather report, with subject Today's Weather report",
        inputs=[Input('email_address'), StepOutput("weather_report")]
    )
    .build()
    ),
    description = "Mail the current weather report of a city" ,
    args = ["city","email_address"]
)

