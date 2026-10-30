"""Real stdio MCP smoke: discovery and all five tools, only synthetic data."""
import asyncio
import json
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root=Path(__file__).resolve().parent.parent
    server=StdioServerParameters(command=sys.executable,args=[str(root/'mcp_server/server.py')])
    async with stdio_client(server) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            listing=await session.list_tools()
            names=sorted(t.name for t in listing.tools)
            expected=['analyze_document','case_statistics','check_parameters','find_similar_cases','legal_reference','search_law','get_law_unit']
            assert names == sorted(expected),names
            cases={
                'analyze_document':{'path':str(root/'samples'/'приговор_пример_ok.docx')},
                'case_statistics':{'article':'158','part':'2'},
                'check_parameters':{'article':'158','part':'2','punishment_type':'лишение свободы','years':6},
                'find_similar_cases':{'query':'кража имущества','article':'158','top_k':3},
                'legal_reference':{'article':'158','part':'2'},
                'search_law':{'query':'частной'},
                'get_law_unit':{'unit_id':'constitution-art-23-minjust-2026-10-29'},
            }
            report={'tools':names,'results':{}}
            for name,arguments in cases.items():
                response=await session.call_tool(name,arguments)
                assert not getattr(response, 'is_error', getattr(response, 'isError', False)),(name,response)
                text='\n'.join(c.text for c in response.content if hasattr(c,'text'))
                assert '"error"' not in text,(name,text)
                if name == 'check_parameters': assert 'OUT_OF_RANGE_MAX' in text
                if name == 'analyze_document': assert 'minimal_structured_report' in text
                report['results'][name]='passed'
            print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    asyncio.run(main())
