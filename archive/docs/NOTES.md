
UI for files

adding/getting files from s3, minIO

switching to logged instead of unlogged

optimized bulk loading via unlogged tables
using mutiple passes?

clean up interfaces pointing to the right level

-- initial tests used lower level but everything
should go through manager

-- adding a table for tasks/jobs?

as there may be multiple vitalgraph instances (in ecs) some coordination on who is doing what task

use celery or similar?

task could be to move term data from import partition to primary partition

this could be a component of an overall import process, which has the separate table for data import, so the data import would need to be updated with progress

the task could update 10,000 terms at a time, allowing indexes to catch up wihtout locking the table much, then repeat until no more terms left.

potentially use postgres signaling for coordination, sending ticks if still working on job? make it easy for others to detect when its not advancing? this is built in with celery?


-- command line/admin scripts also moved to access via manager

testing basic crud operations via client

getting via list of URIs
special cases using endpoints, not sparql?
getting object, getting objects, posting objects, etc.


adding at service level tables for:
import: file --> space/graph
export: space/graph --> file
migrate: space/graph --> space/graph
tracking: cursor over space/graph
checkpoint: timestamp/last hash on space/graph

tracking to use timestamp, offset, hash to help
start/restart a cursor over space/graph that can be used when syncing with external system

checkpoint to use timestamp, hash to identify a 
point in time for a space/graph.  this can help identify when data was synced, backed up, etc.

incorporate using keycloak and jwt for authentication
use in conjunction with a user having access to particular spaces and graphs

endpoints to include parameter for a set of graph uris to allow for a query/modification.  this could be removed once jwt/user are associated with spaces and graphs for enforcing access control.

thus, a sparql query could include an extra parameter in the post for a list of graph uris, and then this can be used when querying the underlying sql tables.

later, the list of graph uris will be determined by the jwt token and user, but the graph uri list will be used in the same way by the underlying sql queries.


after experimentation, adding bulk data can be done using a partition added to the terms table and a partition added to the quads table.

as terms apply to all quads globally, not just the ones in the partition, there needs to be strategy to handle this in combination with turning on indexing of the text and keeping the terms globally unique.

the general flow is:

-- an rdf triples/quads file is parsed and converted into a csv for the quads and a csv for the unique terms.

-- these are loaded into unlogged staging tables in postgresql

-- partitions are added to the term and quad tables using an id specific to the staged data without having any indexes

-- using insert into select, the staged data is inserted into the partitions

-- for the terms, the insert into select should exclude the terms that already exist in the primary term partition (other partitons?)

-- potentially the terms should be merged into the primary partition at this point, which would be adding them to the indexing in the primary partition.

-- queries of the terms could only target the porimary partition by using the partition key, so it wouldn't be finding the terms in the staged partitions

-- quads can remain in the partition with the staged id.

-- queries targeting the quads can target the partitions that have had their respective terms migrated into the primary partition.

-- we can keep a table of partitions and status, and use this info to track when a stated term partition is empty and thus the staged quads partition can be included in the queries.

-- so prior to the quads query we query partitions-status and get a list like: [primary, import_001, import_002, ...] and then use this in dataset in [primary, import_001, import_002, ...] in the query.

-- if desired the data in the partition could be moved into primary and the partition dropped from quads and terms.

-- in the future we could use partitioning to spread data out so there could be N active partitions in both terms and quads, and we push data around using rebalancing via modifying the dataset field.

