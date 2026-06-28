FROM --platform=linux/arm64 eclipse-temurin:17-jre

# Install required packages
RUN apt-get update && \
    apt-get install -y unzip curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r fuseki && useradd -r -g fuseki fuseki

# Set environment variables
ENV FUSEKI_BASE=/fuseki
ENV FUSEKI_HOME=/fuseki
ENV JAVA_OPTIONS="-Xmx2g -Xms1g"

# Create directories
RUN mkdir -p /fuseki /fuseki/databases /fuseki/logs /fuseki/config && \
    chown -R fuseki:fuseki /fuseki

# Copy Fuseki distribution
COPY apache-jena-fuseki-5.6.0.zip /tmp/
RUN cd /tmp && \
    unzip apache-jena-fuseki-5.6.0.zip && \
    mv apache-jena-fuseki-5.6.0/* /fuseki/ && \
    rm -rf /tmp/apache-jena-fuseki-5.6.0* && \
    chmod +x /fuseki/fuseki-server && \
    chown -R fuseki:fuseki /fuseki

# Copy configuration files
COPY config/config.ttl /fuseki/config.ttl
COPY config/shiro.ini /fuseki/shiro.ini

# Create entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set working directory
WORKDIR /fuseki

# Switch to non-root user
USER fuseki

# Expose port
EXPOSE 3030

# Use entrypoint script
ENTRYPOINT ["/entrypoint.sh"]
