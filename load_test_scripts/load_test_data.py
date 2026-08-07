"""Load-test data — populated by setup.py."""

LOAD_TEST_SPACE_ID = "kg_load_test"
LOAD_TEST_GRAPH_ID = "urn:kg_load_test_graph"

ENTITY_DATA = [
    {
        "uri": "http://vital.ai/test/kgentity/organization/techcorp_industries",
        "name": "TechCorp Industries"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/global_finance_group",
        "name": "Global Finance Group"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/healthcare_solutions_inc",
        "name": "Healthcare Solutions Inc"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/energy_innovations_llc",
        "name": "Energy Innovations LLC"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/retail_dynamics_corp",
        "name": "Retail Dynamics Corp"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/manufacturing_excellence",
        "name": "Manufacturing Excellence"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/education_systems_ltd",
        "name": "Education Systems Ltd"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/transportation_networks",
        "name": "Transportation Networks"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/media_and_entertainment_co",
        "name": "Media and Entertainment Co"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/biotech_research_labs",
        "name": "Biotech Research Labs"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/techcorp_industries_#11",
        "name": "TechCorp Industries #11"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/global_finance_group_#12",
        "name": "Global Finance Group #12"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/healthcare_solutions_inc_#13",
        "name": "Healthcare Solutions Inc #13"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/energy_innovations_llc_#14",
        "name": "Energy Innovations LLC #14"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/retail_dynamics_corp_#15",
        "name": "Retail Dynamics Corp #15"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/manufacturing_excellence_#16",
        "name": "Manufacturing Excellence #16"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/education_systems_ltd_#17",
        "name": "Education Systems Ltd #17"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/transportation_networks_#18",
        "name": "Transportation Networks #18"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/media_and_entertainment_co_#19",
        "name": "Media and Entertainment Co #19"
    },
    {
        "uri": "http://vital.ai/test/kgentity/organization/biotech_research_labs_#20",
        "name": "Biotech Research Labs #20"
    }
]

def get_entity_uris():
    return [e['uri'] for e in ENTITY_DATA]

def get_entity_names():
    return [e['name'] for e in ENTITY_DATA]
