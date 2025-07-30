from enum import Enum
from datetime import date, time, datetime
from pytidb.datatype import JSON
from pytidb.schema import TableModel, Field, VectorField, Column
from sqlalchemy import String, Text
from typing import Any, Dict, List
import os
import time
from pytidb import TiDBClient
from pytidb import Session
from pytidb.sql import select
from dotenv import load_dotenv
from pytidb.embeddings import EmbeddingFunction
from pytidb.schema import TableModel, Field, DistanceMetric
from sqlalchemy import text

load_dotenv()

db = TiDBClient.connect(
    host="127.0.0.1",
    port=4000,
    username="root",
    password="",
    database="vitalgraphdb",
)

### Drop all tables

db.drop_table("source")
db.drop_table("tuple")

db.drop_table("space")
db.drop_table("graph")

db.drop_table("cluster_node")
db.drop_table("cluster_edge")

db.drop_table("node")
db.drop_table("edge")
db.drop_table("hyper_node")
db.drop_table("hyper_edge")

db.drop_table("binary")
db.drop_table("document")
db.drop_table("binary_directory")
db.drop_table("document_folder")

db.drop_table("binary_directory_edge")
db.drop_table("document_folder_edge")

### Define Schema

class DataType(Enum):
    # Use string for most text cases
    STRING = "string"
    # Use text just for very long cases
    TEXT = "text"
    # use for all identifiers
    URI = "uri"
    # url used to identify binary storage location
    URL = "url"
    FLOAT = "float"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DATE = "date"
    DATETIME = "datetime"
    GEO_JSON = "geojson"


# OntologySource
class OntologySource(TableModel, table=True):
    __tablename__ = "ontology_source"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))

    source_id: str = Field(sa_column=Column(String(255)))

    ontology_uri: str = Field(sa_column=Column(String(255)))
    ontology_version: str = Field(sa_column=Column(String(255)))
    ontology_update_datetime: datetime = Field()
    ontology_signature: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()


# Tuple
class Tuple(TableModel, table=True):
    __tablename__ = "tuple"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))

    materialized: bool = Field()
    materialized_source_id: str = Field(sa_column=Column(String(255)))
    materialized_datetime: datetime = Field()

    graph: str = Field(sa_column=Column(String(255)))
    subject: str = Field(sa_column=Column(String(1024)))
    predicate: str = Field(sa_column=Column(String(1024)))

    # true if property should be treated as having a list of values
    multi_value: bool = Field()

    value_type: DataType = Field()
    # Text representation of the data value using RDF notation (e.g., "10"^^xsd:int)
    # Use Text data type to hold longer values
    value: str = Field(sa_column=Column(Text))

    value_string: str = Field(sa_column=Column(String(16383)))
    value_text: str = Field(sa_column=Column(Text))
    value_uri: str = Field(sa_column=Column(String(1024)))
    value_url: str = Field(sa_column=Column(String(1024)))
    value_integer: int = Field()
    value_float: float = Field()
    value_date: date = Field()
    value_datetime: datetime = Field()
    value_boolean: bool = Field()
    value_geojson: Dict[str, Any] = Field(sa_column=Column(JSON))
    update_time: datetime = Field()


# Space
class Space(TableModel, table=True):
    __tablename__ = "space"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    space_name: str = Field(sa_column=Column(String(255)))
    space_description: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()


# Graph
class Graph(TableModel, table=True):
    __tablename__ = "graph"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))
    graph_name: str = Field(sa_column=Column(String(255)))
    graph_description: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()


# ClusterNode, ClusterEdge
class ClusterNode(TableModel, table=True):
    __tablename__ = "cluster_node"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))

    cluster_id: str = Field(sa_column=Column(String(1024)))
    update_time: datetime = Field()


class ClusterEdge(TableModel, table=True):
    __tablename__ = "cluster_edge"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    source_uri: str = Field(sa_column=Column(String(255)))
    destination_uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()


# Node, Edge, HyperNode, HyperEdge
class Node(TableModel, table=True):
    __tablename__ = "node"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))
    channel: str = Field(sa_column=Column(String(255)))

    parent_cluster_id: str = Field(sa_column=Column(String(1024)))
    cluster_id: str = Field(sa_column=Column(String(1024)))

    cid_0: bool = Field()
    cid_1: bool = Field()
    cid_2: bool = Field()
    cid_3: bool = Field()
    cid_4: bool = Field()
    cid_5: bool = Field()
    cid_6: bool = Field()
    cid_7: bool = Field()

    uri: str = Field(sa_column=Column(String(255)))

    type_uri: str = Field(sa_column=Column(String(255)))
    type_uri_list: List[str] = Field(sa_column=Column(JSON))

    update_time: datetime = Field()


class Edge(TableModel, table=True):
    __tablename__ = "edge"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))
    channel: str = Field(sa_column=Column(String(255)))

    parent_cluster_id: str = Field(sa_column=Column(String(1024)))
    cluster_id: str = Field(sa_column=Column(String(1024)))

    cid_0: bool = Field()
    cid_1: bool = Field()
    cid_2: bool = Field()
    cid_3: bool = Field()
    cid_4: bool = Field()
    cid_5: bool = Field()
    cid_6: bool = Field()
    cid_7: bool = Field()

    uri: str = Field(sa_column=Column(String(255)))
    source_uri: str = Field(sa_column=Column(String(255)))
    destination_uri: str = Field(sa_column=Column(String(255)))

    type_uri: str = Field(sa_column=Column(String(255)))
    type_uri_list: List[str] = Field(sa_column=Column(JSON))

    update_time: datetime = Field()


class HyperNode(TableModel, table=True):
    __tablename__ = "hyper_node"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))
    channel: str = Field(sa_column=Column(String(255)))

    parent_cluster_id: str = Field(sa_column=Column(String(1024)))
    cluster_id: str = Field(sa_column=Column(String(1024)))

    cid_0: bool = Field()
    cid_1: bool = Field()
    cid_2: bool = Field()
    cid_3: bool = Field()
    cid_4: bool = Field()
    cid_5: bool = Field()
    cid_6: bool = Field()
    cid_7: bool = Field()

    uri: str = Field(sa_column=Column(String(255)))

    type_uri: str = Field(sa_column=Column(String(255)))
    type_uri_list: List[str] = Field(sa_column=Column(JSON))

    update_time: datetime = Field()


class HyperEdge(TableModel, table=True):
    __tablename__ = "hyper_edge"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))
    channel: str = Field(sa_column=Column(String(255)))

    parent_cluster_id: str = Field(sa_column=Column(String(1024)))
    cluster_id: str = Field(sa_column=Column(String(1024)))

    cid_0: bool = Field()
    cid_1: bool = Field()
    cid_2: bool = Field()
    cid_3: bool = Field()
    cid_4: bool = Field()
    cid_5: bool = Field()
    cid_6: bool = Field()
    cid_7: bool = Field()

    uri: str = Field(sa_column=Column(String(255)))
    source_uri: str = Field(sa_column=Column(String(255)))
    destination_uri: str = Field(sa_column=Column(String(255)))

    type_uri: str = Field(sa_column=Column(String(255)))
    type_uri_list: List[str] = Field(sa_column=Column(JSON))

    update_time: datetime = Field()



# Binary
class Binary(TableModel, table=True):
    __tablename__ = "binary"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()


# Document
class Document(TableModel, table=True):
    __tablename__ = "document"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()



# BinaryDirectory, BinaryDirectoryEdge
class BinaryDirectory(TableModel, table=True):
    __tablename__ = "binary_directory"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()



class BinaryDirectoryEdge(TableModel, table=True):
    __tablename__ = "binary_directory_edge"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    source_uri: str = Field(sa_column=Column(String(255)))
    destination_uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()


# DocumentFolder, DocumentFolderEdge
class DocumentFolder(TableModel, table=True):
    __tablename__ = "document_folder"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()



class DocumentFolderEdge(TableModel, table=True):
    __tablename__ = "document_folder_edge"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    tenant: str = Field(sa_column=Column(String(255)))
    space: str = Field(sa_column=Column(String(255)))
    graph: str = Field(sa_column=Column(String(255)))

    uri: str = Field(sa_column=Column(String(255)))
    source_uri: str = Field(sa_column=Column(String(255)))
    destination_uri: str = Field(sa_column=Column(String(255)))
    update_time: datetime = Field()



### create tables

source_table = db.create_table(schema=OntologySource)

tuple_table = db.create_table(schema=Tuple)

space_table = db.create_table(schema=Space)

graph_table = db.create_table(schema=Graph)

cluster_node_table = db.create_table(schema=ClusterNode)

cluster_edge_table = db.create_table(schema=ClusterEdge)

node_table = db.create_table(schema=Node)

edge_table = db.create_table(schema=Edge)

hyper_node_table = db.create_table(schema=HyperNode)

hyper_edge_table = db.create_table(schema=HyperEdge)

binary_table = db.create_table(schema=Binary)

document_table = db.create_table(schema=Document)

binary_directory_table = db.create_table(schema=BinaryDirectory)

binary_directory_edge_table = db.create_table(schema=BinaryDirectoryEdge)

document_folder_table = db.create_table(schema=DocumentFolder)

document_folder_edge_table = db.create_table(schema=DocumentFolderEdge)






