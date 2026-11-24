

def add_clusters_pageRank_Database(driver, tool_nodes):
    """
    Add clusters to the database graph and calculate PageRank and Louvain community detection.

    This function will delete all the previous graph and create a new one.
    It will also calculate the PageRank and Louvain community detection for all the nodes in the graph.
    The results will be stored in the graph as node properties.

    :param driver: The driver to connect to the graph database
    :param tool_nodes: The list of tool nodes to add to the graph
    """
    with driver.session() as session:
        print("Removing nodes with 0 interactions")
        # Remove nodes with no interactions
        session.run("""
            MATCH (n)
            WHERE size((n)--())=0
            DELETE (n)
            """)
        
        print("Add topics to the Tools")
        session.run("""
            match (i:Tool)-[:TOPIC]->(k:Keyword)
            with i, collect(k.edam) as cedam, collect(k.label) as clabel
            set i.topiclabel=clabel
            set i.topicedam =cedam
            return distinct *
            """)
        
        print("Add TypeTool to the Tools")
        session.run("""
            match (i:Tool)-[:HAS_TYPE]->(k:TypeTool)
            with i, collect(k.name) as cname
            set i.toolType=cname
            return distinct *
            """)
        
        print("Add Databases nodes")
        session.run("""
            match (i:Tool)
            where "db" in i.toolType
            WITH collect(i) AS databases
            // With an empty list, APOC relabels every Tool node
            WHERE size(databases) > 0
            CALL apoc.refactor.rename.label("Tool", "Database", databases)
            YIELD committedOperations
            RETURN committedOperations
            """)
        # Remove previous nodes and edges
        session.run("""MATCH ()-[r:METAOCCUR_COMM]->() DELETE r""")
        session.run("""MATCH ()-[r:HAS_COMMUNITY]->() DELETE r""")
        session.run("""MATCH (r:Community) DELETE r""")
        
        print("Creating view")
        ### PageRank
        # Create view with the property
        session.run("""
            CALL gds.graph.create(
            'got-weighted-interactions',
            ['Tool', 'Publication', 'Database'],
            {
                METAOCCUR_ALL: {
                    orientation: 'UNDIRECTED',
                    aggregation: 'NONE',
                    properties: {
                        times: {
                        property: 'times',
                        aggregation: 'NONE',
                        defaultValue: 0.0
                        }
                    }
                }
            }
            )
            """)
        print("PageRank")
        # Write PageRank values to each node
        session.run("""
            CALL gds.pageRank.write(
                'got-weighted-interactions', 
                {
                    relationshipWeightProperty: 'times',
                    writeProperty: 'pageRank'
                }
            )
            """)
        print("Louvain")
        # Write the community id to each node
        session.run("""
            CALL gds.louvain.write(
                'got-weighted-interactions',
                {
                    relationshipWeightProperty: 'times',
                    writeProperty: 'community'
                }
            )
            """)
        # Remove the in-memory GDS graph now (not used after Louvain), so its
        # heap is free for the community steps below
        session.run("""
            CALL gds.graph.drop('got-weighted-interactions')
        """)

        print("Create clusters for all dataset")
        # Create clusters as nodes
        session.run("""
            MATCH (n) 
            WITH distinct n.community as com
            CREATE (:Community {com_id: com})
            """)
    community_membership_edges(driver)
    community_edges_and_properties(driver)


def community_membership_edges(driver):
    """
    Edges between each node and its community (HAS_COMMUNITY).
    Needs the Community nodes and the community property from Louvain.
    Uses an index on Community(com_id) and batches, so it does not build
    the cartesian product of all nodes and communities in memory.
    """
    with driver.session() as session:
        print("Creating edges between nodes and communities (HAS_COMMUNITY)")
        session.run("""CREATE INDEX IF NOT EXISTS FOR (c:Community) ON (c.com_id)""")
        session.run("""CALL db.awaitIndexes(600)""")
        # Remove previous ones, if any, so running it again does not duplicate them
        session.run("""
            MATCH ()-[r:HAS_COMMUNITY]->()
            CALL { WITH r DELETE r } IN TRANSACTIONS OF 10000 ROWS
            """)
        session.run("""
            MATCH (n) WHERE n.community IS NOT NULL
            CALL {
                WITH n
                MATCH (i:Community {com_id: n.community})
                CREATE (n)-[:HAS_COMMUNITY]->(i)
            } IN TRANSACTIONS OF 10000 ROWS
            """)


def community_edges_and_properties(driver):
    """
    Create the METAOCCUR_COMM edges between communities and the community
    properties (most common topic, language and OS).

    Needs the Community nodes and HAS_COMMUNITY edges already in the graph.

    :param driver: The driver to connect to the graph database
    """
    with driver.session() as session:
        print("Creating edges between communities (METAOCCUR_COMM)")
        session.run("""MATCH ()-[r:METAOCCUR_COMM]->() DELETE r""")
        # One community at a time, in batches: summing all METAOCCUR_ALL
        # edges in a single transaction runs out of heap
        session.run("""
            MATCH (c1:Community)
            CALL {
                WITH c1
                MATCH (c1)<-[:HAS_COMMUNITY]-(n)-[m:METAOCCUR_ALL]-(p)-[:HAS_COMMUNITY]->(c2:Community)
                WHERE c1 <> c2
                WITH c1, c2, sum(m.times) AS sumo
                CREATE (c1)-[:METAOCCUR_COMM {times: sumo}]->(c2)
            } IN TRANSACTIONS OF 100 ROWS
            """)
        # Delete duplicated and reversed relationships
        session.run("""
            Match (c1:Community)-[r:METAOCCUR_COMM]->(c2:Community)
            where c1.com_id < c2.com_id
            delete r
            """)

        #################### Create community properties #######################
        
        print("Creating community properties")
        ### Add most common topics in the communities
        # Empty topic for all the communities
        session.run("""
            MATCH (n:Community)
            set n.mtopic=NULL, n.ctopic=NULL
            return n.mtopic,n.ctopic
            """)
        # Topics for communities bigger than 1
        session.run("""
            Match (l:Keyword)<-[:TOPIC]-(i)-[:HAS_COMMUNITY]->(c)
            with c,l,count(i) as counti
            order by counti DESC
            with c,collect(l)[0] as mtopic, max(counti) as maxcount
            set c.mtopic=mtopic.label, c.ctopic=id(mtopic)
            return c,mtopic, maxcount
            """)
        ### Add most common languages in the communities
        # Empty language for all the communities
        session.run("""
            MATCH (n:Community)
            set n.mlanguage=NULL, n.clanguage=NULL
            return n.mtopic,n.ctopic
            """)
        # Languages for communities bigger than 1
        session.run("""
            Match (l:Language)<-[:USE_LANGUAGE]-(i)-[:HAS_COMMUNITY]->(c)
            with c,l,count(i) as counti
            order by counti DESC
            with c,collect(l)[0] as mlanguage, max(counti) as maxcount
            set c.mlanguage=mlanguage.name, c.clanguage=id(mlanguage)
            return c,mlanguage, maxcount
            """)
        ### Add most common Operative system in the community
        # Empty OS for all the communities
        session.run("""
            MATCH (n:Community)
            set n.mos=NULL, n.cos=NULL
            return n.mtopic,n.ctopic
            """)
        # OS for communities bigger than 1
        session.run("""
            Match (l:OS)<-[:USE_OS]-(i)-[:HAS_COMMUNITY]->(c)
            with c,l,count(i) as counti
            order by counti DESC
            with c,collect(l)[0] as mlanguage, max(counti) as maxcount
            set c.mos=mlanguage.name, c.cos=id(mlanguage)
            return c,mlanguage, maxcount
            """)
