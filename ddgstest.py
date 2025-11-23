from ddgs import DDGS

def test_ddgs_query():
    results = DDGS().text(
        query="servosys solutions leadership and key stakeholders",
        region="in-en",
        max_results=10,
        backend="google"
    )

    for result in results:
        print(f"Title: {result['title']}")
        print(f"URL: {result['href']}")
        print(f"Description: {result['body']}\n")

test_ddgs_query()