from setuptools import setup, find_packages
import os

# Create MANIFEST.in file if it doesn't exist
manifest_content = """
# Include frontend build files
recursive-include vitalgraph/api/frontend/dist *
# Include README and license files
include README.md
include LICENSE
"""

with open('MANIFEST.in', 'w') as f:
    f.write(manifest_content)

setup(
    name='vital-graph',
    version='0.0.3',
    author='Marc Hadfield',
    author_email='marc@vital.ai',
    description='VitalGraph',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/vital-ai/vital-graph',
    packages=find_packages(exclude=["test", "test_scripts", "rdflib_sqlalchemy"]),
    include_package_data=True,  # This tells setuptools to include files from MANIFEST.in
    entry_points={
        'console_scripts': [
            'vitalgraphdb=vitalgraph.main.main:run_server',
        ],
    },

    license='Apache License 2.0',
    install_requires=[
        "vital-ai-vitalsigns>=0.1.31",
        "pytidb[models]",
        "pytidb",
        "python-dotenv",
        # "rdflib>=7.1.4",
        "rdflib>=7.0.0",
        "six>=1.7.0",
        "alembic>=0.8.8",
        "SQLAlchemy[asyncio]>=2.0.23",
        'pgvector',
        'asyncpg',
        'openai',
        "psycopg[binary,pool]>=3.1.13",
        # 'greenlet',
        'aiofiles',
        'fastapi[standard, models]',
        'uvicorn',
        'Jinja2',
        'starlette',
        'itsdangerous',
        'click-repl',
        'tabulate'
    ],

    classifiers=[
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.11',
)
