"""
100 test entities for dedup testing.

Covers: exact duplicates, near-duplicates, phonetic variants, typos,
aliases, abbreviations, different entity types, different countries,
short names, long names, multi-word names, and unrelated entities.

Usage:
    from test_dedup_entities import TEST_ENTITIES
"""

TEST_ENTITIES = [
    # ---------------------------------------------------------------
    # Cluster 1: Acme Corporation variants (business, US)
    # ---------------------------------------------------------------
    ('e_001', {
        'primary_name': 'Acme Corporation',
        'type_key': 'business',
        'country': 'US',
        'region': 'California',
        'aliases': [{'alias_name': 'ACME'}, {'alias_name': 'Acme Corp'}],
    }),
    ('e_002', {
        'primary_name': 'Acme Corp',
        'type_key': 'business',
        'country': 'US',
        'region': 'California',
    }),
    ('e_003', {
        'primary_name': 'ACME Corporation Inc',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_004', {
        'primary_name': 'Acme Corporaton',  # typo: missing 'i'
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_005', {
        'primary_name': 'Acme Corproation',  # typo: transposition
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 2: Smith & Associates (same name, different locations)
    # ---------------------------------------------------------------
    ('e_006', {
        'primary_name': 'Smith & Associates',
        'type_key': 'business',
        'country': 'US',
        'region': 'New York',
    }),
    ('e_007', {
        'primary_name': 'Smith & Associates',
        'type_key': 'business',
        'country': 'UK',
        'region': 'London',
    }),
    ('e_008', {
        'primary_name': 'Smith and Associates',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_009', {
        'primary_name': 'Smtih & Associates',  # typo: transposition
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_010', {
        'primary_name': 'Smythe & Associates',  # phonetic variant
        'type_key': 'business',
        'country': 'UK',
    }),

    # ---------------------------------------------------------------
    # Cluster 3: IBM / International Business Machines
    # ---------------------------------------------------------------
    ('e_011', {
        'primary_name': 'International Business Machines',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'IBM'}, {'alias_name': 'Big Blue'}],
    }),
    ('e_012', {
        'primary_name': 'IBM',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_013', {
        'primary_name': 'International Buisness Machines',  # typo
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 4: Schneider / Snyder / Snider (phonetic variants)
    # ---------------------------------------------------------------
    ('e_014', {
        'primary_name': 'Schneider Industries',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_015', {
        'primary_name': 'Snyder Industries',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_016', {
        'primary_name': 'Snider Industries',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_017', {
        'primary_name': 'Schnider Industries',  # typo of Schneider
        'type_key': 'business',
        'country': 'DE',
    }),

    # ---------------------------------------------------------------
    # Cluster 5: Schmidt / Schmitt / Schmid (phonetic variants)
    # ---------------------------------------------------------------
    ('e_018', {
        'primary_name': 'Schmidt Manufacturing',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_019', {
        'primary_name': 'Schmitt Manufacturing',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_020', {
        'primary_name': 'Schmid Manufacturing',
        'type_key': 'business',
        'country': 'CH',
    }),

    # ---------------------------------------------------------------
    # Cluster 6: Meyer / Meier / Mayer / Maier (phonetic variants)
    # ---------------------------------------------------------------
    ('e_021', {
        'primary_name': 'Meyer Financial Group',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_022', {
        'primary_name': 'Meier Financial Group',
        'type_key': 'business',
        'country': 'CH',
    }),
    ('e_023', {
        'primary_name': 'Mayer Financial Group',
        'type_key': 'business',
        'country': 'AT',
    }),
    ('e_024', {
        'primary_name': 'Maier Financial Group',
        'type_key': 'business',
        'country': 'DE',
    }),

    # ---------------------------------------------------------------
    # Cluster 7: National Bank variants
    # ---------------------------------------------------------------
    ('e_025', {
        'primary_name': 'National Bank of Commerce',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'NBC'}],
    }),
    ('e_026', {
        'primary_name': 'National Bank of Commerce Inc',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_027', {
        'primary_name': 'National Bank Corp',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_028', {
        'primary_name': 'National Banking Group',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_029', {
        'primary_name': 'Natonal Bank of Commerce',  # typo: missing 'i'
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 8: Johnson / Johansson / Johanson (phonetic variants)
    # ---------------------------------------------------------------
    ('e_030', {
        'primary_name': 'Johnson & Partners',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_031', {
        'primary_name': 'Johansson & Partners',
        'type_key': 'business',
        'country': 'SE',
    }),
    ('e_032', {
        'primary_name': 'Johanson & Partners',
        'type_key': 'business',
        'country': 'SE',
    }),
    ('e_033', {
        'primary_name': 'Johnsen & Partners',
        'type_key': 'business',
        'country': 'NO',
    }),

    # ---------------------------------------------------------------
    # Cluster 9: Stephens / Stevens / Stefan (phonetic variants)
    # ---------------------------------------------------------------
    ('e_034', {
        'primary_name': 'Stephens Legal Group',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_035', {
        'primary_name': 'Stevens Legal Group',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_036', {
        'primary_name': 'Stefan Legal Group',
        'type_key': 'business',
        'country': 'DE',
    }),

    # ---------------------------------------------------------------
    # Cluster 10: Pfizer / Phizer (phonetic variant)
    # ---------------------------------------------------------------
    ('e_037', {
        'primary_name': 'Pfizer Pharmaceuticals',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'Pfizer'}],
    }),
    ('e_038', {
        'primary_name': 'Phizer Pharmaceuticals',  # phonetic variant
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_039', {
        'primary_name': 'Pzifer Pharmaceuticals',  # typo: transposition
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 11: Person names — Martinez / Martin / Martinson
    # ---------------------------------------------------------------
    ('e_040', {
        'primary_name': 'Bob Martinez',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_041', {
        'primary_name': 'Robert Martinez',
        'type_key': 'person',
        'country': 'US',
        'aliases': [{'alias_name': 'Bob Martinez'}],
    }),
    ('e_042', {
        'primary_name': 'Roberto Martinez',
        'type_key': 'person',
        'country': 'MX',
    }),
    ('e_043', {
        'primary_name': 'Bob Martin',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_044', {
        'primary_name': 'Bob Martinson',
        'type_key': 'person',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 12: Person names — Catherine / Kathy / Cathy
    # ---------------------------------------------------------------
    ('e_045', {
        'primary_name': 'Catherine Williams',
        'type_key': 'person',
        'country': 'US',
        'aliases': [{'alias_name': 'Cathy Williams'}, {'alias_name': 'Kate Williams'}],
    }),
    ('e_046', {
        'primary_name': 'Kathy Williams',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_047', {
        'primary_name': 'Cathy Williams',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_048', {
        'primary_name': 'Kathryn Williams',
        'type_key': 'person',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 13: Global Solutions / Global Systems (similar names)
    # ---------------------------------------------------------------
    ('e_049', {
        'primary_name': 'Global Solutions Inc',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_050', {
        'primary_name': 'Global Solutions International',
        'type_key': 'business',
        'country': 'UK',
    }),
    ('e_051', {
        'primary_name': 'Global Systems Inc',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_052', {
        'primary_name': 'Globel Solutions Inc',  # typo
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 14: Technology companies (distinct but same domain)
    # ---------------------------------------------------------------
    ('e_053', {
        'primary_name': 'Microsoft Corporation',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'MSFT'}, {'alias_name': 'Microsoft'}],
    }),
    ('e_054', {
        'primary_name': 'Microsft Corporation',  # typo: missing 'o'
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_055', {
        'primary_name': 'Apple Inc',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'AAPL'}, {'alias_name': 'Apple'}],
    }),
    ('e_056', {
        'primary_name': 'Google LLC',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'Alphabet'}, {'alias_name': 'GOOGL'}],
    }),
    ('e_057', {
        'primary_name': 'Amazon.com Inc',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'Amazon'}, {'alias_name': 'AMZN'}],
    }),

    # ---------------------------------------------------------------
    # Cluster 15: Short names (vulnerable to shingle breakdown)
    # ---------------------------------------------------------------
    ('e_058', {
        'primary_name': 'AIG',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_059', {
        'primary_name': 'ABB',
        'type_key': 'business',
        'country': 'CH',
    }),
    ('e_060', {
        'primary_name': 'SAP',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_061', {
        'primary_name': 'UBS',
        'type_key': 'business',
        'country': 'CH',
    }),
    ('e_062', {
        'primary_name': 'BMW',
        'type_key': 'business',
        'country': 'DE',
        'aliases': [{'alias_name': 'Bayerische Motoren Werke'}],
    }),

    # ---------------------------------------------------------------
    # Cluster 16: Anderson / Andersen / Henderson
    # ---------------------------------------------------------------
    ('e_063', {
        'primary_name': 'Anderson Consulting',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_064', {
        'primary_name': 'Andersen Consulting',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_065', {
        'primary_name': 'Henderson Consulting',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_066', {
        'primary_name': 'Andreson Consulting',  # typo: transposition
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 17: Thompson / Thomson / Tompson
    # ---------------------------------------------------------------
    ('e_067', {
        'primary_name': 'Thompson Reuters',
        'type_key': 'business',
        'country': 'CA',
    }),
    ('e_068', {
        'primary_name': 'Thomson Reuters',
        'type_key': 'business',
        'country': 'CA',
    }),
    ('e_069', {
        'primary_name': 'Tompson Reuters',  # phonetic variant
        'type_key': 'business',
        'country': 'CA',
    }),

    # ---------------------------------------------------------------
    # Cluster 18: Deutsche / German company names
    # ---------------------------------------------------------------
    ('e_070', {
        'primary_name': 'Deutsche Bank AG',
        'type_key': 'business',
        'country': 'DE',
        'aliases': [{'alias_name': 'Deutsche Bank'}],
    }),
    ('e_071', {
        'primary_name': 'Deutsche Telekom AG',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_072', {
        'primary_name': 'Deutche Bank AG',  # typo: missing 's'
        'type_key': 'business',
        'country': 'DE',
    }),

    # ---------------------------------------------------------------
    # Cluster 19: Law firms with similar patterns
    # ---------------------------------------------------------------
    ('e_073', {
        'primary_name': 'Baker McKenzie',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_074', {
        'primary_name': 'Baker & McKenzie',
        'type_key': 'business',
        'country': 'US',
    }),
    ('e_075', {
        'primary_name': 'Baker MacKenzie',  # phonetic variant
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 20: Person names — Williams / Williamson / Wilson
    # ---------------------------------------------------------------
    ('e_076', {
        'primary_name': 'James Williams',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_077', {
        'primary_name': 'James Williamson',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_078', {
        'primary_name': 'James Wilson',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_079', {
        'primary_name': 'James Willams',  # typo: missing 'i'
        'type_key': 'person',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 21: Healthcare / Pharma
    # ---------------------------------------------------------------
    ('e_080', {
        'primary_name': 'Johnson & Johnson',
        'type_key': 'business',
        'country': 'US',
        'aliases': [{'alias_name': 'J&J'}, {'alias_name': 'JNJ'}],
    }),
    ('e_081', {
        'primary_name': 'Jonson & Johnson',  # typo: missing 'h'
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 22: Unrelated entities (noise / negative cases)
    # ---------------------------------------------------------------
    ('e_082', {
        'primary_name': 'Sunshine Bakery',
        'type_key': 'business',
        'country': 'US',
        'region': 'Florida',
    }),
    ('e_083', {
        'primary_name': 'Pacific Ocean Fisheries',
        'type_key': 'business',
        'country': 'JP',
    }),
    ('e_084', {
        'primary_name': 'Mountain View Landscaping',
        'type_key': 'business',
        'country': 'US',
        'region': 'Colorado',
    }),
    ('e_085', {
        'primary_name': 'Sahara Desert Tours',
        'type_key': 'business',
        'country': 'MA',
    }),
    ('e_086', {
        'primary_name': 'Evergreen Forest Products',
        'type_key': 'business',
        'country': 'CA',
    }),

    # ---------------------------------------------------------------
    # Cluster 23: Long multi-word names
    # ---------------------------------------------------------------
    ('e_087', {
        'primary_name': 'First National Community Bank of Northern California',
        'type_key': 'business',
        'country': 'US',
        'region': 'California',
    }),
    ('e_088', {
        'primary_name': 'First National Community Bank of Southern California',
        'type_key': 'business',
        'country': 'US',
        'region': 'California',
    }),
    ('e_089', {
        'primary_name': 'First Natoinal Community Bank of Northern California',  # typo
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 24: O'Brien / Obrien / O Brian
    # ---------------------------------------------------------------
    ('e_090', {
        'primary_name': "Patrick O'Brien",
        'type_key': 'person',
        'country': 'IE',
    }),
    ('e_091', {
        'primary_name': 'Patrick Obrien',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_092', {
        'primary_name': 'Patrick O Brian',
        'type_key': 'person',
        'country': 'IE',
    }),

    # ---------------------------------------------------------------
    # Cluster 25: Muller / Mueller / Miller (phonetic variants)
    # ---------------------------------------------------------------
    ('e_093', {
        'primary_name': 'Muller Engineering',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_094', {
        'primary_name': 'Mueller Engineering',
        'type_key': 'business',
        'country': 'DE',
    }),
    ('e_095', {
        'primary_name': 'Miller Engineering',
        'type_key': 'business',
        'country': 'US',
    }),

    # ---------------------------------------------------------------
    # Cluster 26: Li / Lee / Leigh (short phonetic variants)
    # ---------------------------------------------------------------
    ('e_096', {
        'primary_name': 'David Li',
        'type_key': 'person',
        'country': 'CN',
    }),
    ('e_097', {
        'primary_name': 'David Lee',
        'type_key': 'person',
        'country': 'US',
    }),
    ('e_098', {
        'primary_name': 'David Leigh',
        'type_key': 'person',
        'country': 'UK',
    }),

    # ---------------------------------------------------------------
    # Cluster 27: Garcia / Garsia / Gracia
    # ---------------------------------------------------------------
    ('e_099', {
        'primary_name': 'Maria Garcia',
        'type_key': 'person',
        'country': 'MX',
    }),
    ('e_100', {
        'primary_name': 'Maria Garsia',  # phonetic variant
        'type_key': 'person',
        'country': 'MX',
    }),
]
