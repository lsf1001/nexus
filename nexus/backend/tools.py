import datetime
from langchain_core.tools import tool as langchain_tool
from langchain_community.tools import DuckDuckGoSearchRun


@langchain_tool
def get_current_date() -> str:
    """获取今天的日期，格式 YYYY-MM-DD。"""
    today = datetime.date.today()
    return today.strftime("%Y-%m-%d")


web_search = DuckDuckGoSearchRun(name="web_search", description="搜索网络信息")

TOOLS = [get_current_date, web_search]