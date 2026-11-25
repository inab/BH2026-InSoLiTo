"""
Compare node and relationship counts between two InSoLiTo Neo4j databases.

Goal: after rebuilding the database with the pipeline, check that the new
numbers are reasonable compared with the database currently in production,
before replacing it.

- Read-only: every query is a count (MATCH ... RETURN count(...)).
- Uses the Neo4j HTTP endpoint (/db/neo4j/tx/commit), the same one the web uses,
  so it works for production (through Apache) and for a local Neo4j.
- Prints one row per node label and relationship type: reference, new,
  difference and ratio (new / reference).

Run from the repo root, with the local Neo4j up:
    .venv/bin/python DB/pipeline/compare_counts.py
"""
import json
import urllib.request

# Database used as reference (production) and the new one (local)
REFERENCE_URL = 'https://insolito.openebench.bsc.es/db/neo4j/tx/commit'
NEW_URL = 'http://localhost:7474/db/neo4j/tx/commit'

NODE_LABELS = ['Tool', 'Database', 'Publication', 'Keyword', 'Community',
               'Language', 'OS', 'TypeTool']
REL_TYPES = ['METAOCCUR', 'METAOCCUR_ALL', 'METAOCCUR_COMM', 'HAS_COMMUNITY',
             'TOPIC', 'OPERATION', 'SUBCLASS', 'CITED_BEFORE', 'WORKFLOW_NEXT']

QUERIES = ([(f':{label}', f'MATCH (n:{label}) RETURN count(n)') for label in NODE_LABELS]
           + [(f'[:{rel}]', f'MATCH ()-[r:{rel}]->() RETURN count(r)') for rel in REL_TYPES])


def run_counts(url):
    """Send all count queries in one request and return {name: count}."""
    body = json.dumps({'statements': [{'statement': q} for _, q in QUERIES]}).encode()
    request = urllib.request.Request(url, data=body,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=600) as response:
        answer = json.load(response)
    if answer.get('errors'):
        raise SystemExit(f'Error from {url}: {answer["errors"]}')
    return {name: result['data'][0]['row'][0]
            for (name, _), result in zip(QUERIES, answer['results'])}


reference = run_counts(REFERENCE_URL)
new = run_counts(NEW_URL)

print(f'Reference: {REFERENCE_URL}')
print(f'New:       {NEW_URL}\n')
print(f'{"":18}{"reference":>14}{"new":>14}{"difference":>14}{"ratio":>8}')
for name, _ in QUERIES:
    ref, cur = reference[name], new[name]
    ratio = f'{cur / ref:.2f}' if ref else '-'
    print(f'{name:18}{ref:>14,}{cur:>14,}{cur - ref:>+14,}{ratio:>8}')
