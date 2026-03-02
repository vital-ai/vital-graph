# Stage 1: Build
FROM eclipse-temurin:21-jdk AS build
RUN apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pom.xml .
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -q -DskipTests

# Stage 2: Run
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/sparql-compiler-sidecar-1.0.0.jar app.jar

ENV PORT=7070
ENV MAX_INPUT_SIZE=1048576
ENV REQUEST_TIMEOUT_MS=5000

EXPOSE 7070

ENTRYPOINT ["java", "-Xmx256m", "-jar", "app.jar"]
