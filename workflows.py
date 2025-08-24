from portia import PlanBuilderV2, StepOutput, Input


daily_news_plan = (
    PlanBuilderV2("Fetch trending news, create a concise summary of the news")
    .invoke_tool_step(
        tool ="portia:tavily::search",
        args = {'search_query' : 'latest trending news'}, 
        step_name = "search_news"
    )
    .llm_step(
        task = """Summarize in simple the raw news data into a structured format:
        
        For each news article, provide:
        - Headline: Clear, engaging title
        - Summary: Concise 1-2 line summary of the key points
        - Link: URL to the full article
        
        Format as a clean, readable list.
        REPLY IN MARKDOWn
        """,
        inputs=[StepOutput("search_news")],
        step_name="news_summary"
    )
    .build()
)

tech_digest_plan = (
    PlanBuilderV2("Research latest tech innovations and create an executive summary")
    .invoke_tool_step(
        tool="portia:tavily::search",
        args={'search_query': 'latest technology innovations AI startups 2024'},
        step_name="search_tech_news"
    )
    .llm_step(
        task="""Filter and categorize the technology news into key areas:
        
        Organize the findings into these categories:
        - AI & Machine Learning: Latest developments and breakthroughs
        - Startups & Funding: New companies and investment rounds
        - Product Launches: Major tech product announcements
        - Industry Trends: Emerging patterns and market shifts
        
        For each category, list 2-3 most significant items with brief descriptions.""",
        inputs=[StepOutput("search_tech_news")],
        step_name="categorize_tech"
    )
    .invoke_tool_step(
        tool="portia:tavily::search",
        args={'search_query': 'technology market analysis trends impact business'},
        step_name="search_market_impact"
    )
    .llm_step(
        task="""Create an executive summary in combining tech innovations with market impact:
        
        Structure the final report as:
        - Executive Overview: 2-3 sentence summary of key trends
        - Innovation Highlights: Top 3 most impactful developments
        - Business Implications: How these trends affect different industries
        - Watch List: 2-3 technologies or companies to monitor
        
        Target audience: Business executives and tech decision makers.
        Keep it strategic and actionable.
        REPLY IN MARKDOWN
        """,
        inputs=[StepOutput("categorize_tech"), StepOutput("search_market_impact")],
        step_name="executive_summary"
    )
    .build()
)