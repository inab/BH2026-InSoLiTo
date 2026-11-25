

def citations_edges(driver, Metacitations_file):
    """
    Delete all edges METAOCCUR and METAOCCUR_ALL from the graph.
    Create new edges METAOCCUR and METAOCCUR_ALL with the data from the csv file.
    The csv file must contain the columns id1, id2, n_citations and year.
    The edges are created from the node id1 to the node id2 with the properties
    times and year.
    After creating all the edges METAOCCUR, a new edge METAOCCUR_ALL is created
    from each node to all the nodes that have an edge METAOCCUR with it.
    The property times of the edge METAOCCUR_ALL is the sum of all the properties
    times of the edges METAOCCUR.
    """
    with driver.session() as session:
        session.run("""MATCH ()-[r:METAOCCUR]->() DELETE r""")
        session.run("""MATCH ()-[r:METAOCCUR_ALL]->() DELETE r""")

        print("Tool-Publication citations")
        session.run("""
            LOAD CSV WITH HEADERS FROM "file:///%s" AS csv
            CALL {
                WITH csv
                MATCH (t:Tool {label:csv.id1}),(p:Publication {pmid:csv.id2})
                CREATE (t)-[:METAOCCUR {times:toInteger(csv.n_citations), year:toInteger(csv.year)}]->(p)
            } IN TRANSACTIONS OF 10000 ROWS
        """ % Metacitations_file)
        session.run("""
            LOAD CSV WITH HEADERS FROM "file:///%s" AS csv
            CALL {
                WITH csv
                MATCH (t:Tool {label:csv.id2}),(p:Publication {pmid:csv.id1})
                CREATE (t)-[:METAOCCUR {times:toInteger(csv.n_citations), year:toInteger(csv.year)}]->(p)
            } IN TRANSACTIONS OF 10000 ROWS
        """ % Metacitations_file)

        print("Tool-Tool citations")
        session.run("""
            LOAD CSV WITH HEADERS FROM "file:///%s" AS csv
            CALL {
                WITH csv
                MATCH (t:Tool {label:csv.id1}),(t2:Tool {label:csv.id2})
                CREATE (t)-[:METAOCCUR {times:toInteger(csv.n_citations), year:toInteger(csv.year)}]->(t2)
            } IN TRANSACTIONS OF 10000 ROWS
        """ % Metacitations_file)
        
    metaoccur_all_edges(driver)


def metaoccur_all_edges(driver):
    """
    Create one METAOCCUR_ALL edge per pair with the sum of the METAOCCUR
    times of all years. Deletes any previous METAOCCUR_ALL first, so it can
    be run again on its own.
    Only Tool nodes have outgoing METAOCCUR edges (Database labels are set
    later, in DataScience.py). Small batches (10 tools) because a very cited
    tool can have hundreds of thousands of METAOCCUR edges.
    """
    with driver.session() as session:
        session.run("""
            MATCH ()-[r:METAOCCUR_ALL]->()
            CALL { WITH r DELETE r } IN TRANSACTIONS OF 10000 ROWS
            """)
        print("Sum of citations of all years (METAOCCUR_ALL)")
        session.run("""
            MATCH (t:Tool)
            CALL {
                WITH t
                MATCH (t)-[m:METAOCCUR]->(p)
                WITH t, p, sum(m.times) AS sumo
                CREATE (t)-[:METAOCCUR_ALL {times: sumo}]->(p)
            } IN TRANSACTIONS OF 10 ROWS
            """)