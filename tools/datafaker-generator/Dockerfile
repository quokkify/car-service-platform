FROM eclipse-temurin:25.0.4_7-jdk@sha256:97014c4b396021f9ddb7d592a7dbedb0c4e4215c29e03dc01c393558aefb71c2 AS builder

WORKDIR /src

COPY gradle gradle
COPY gradlew gradlew.bat settings.gradle.kts build.gradle.kts ./
RUN ./gradlew --no-daemon dependencies >/dev/null

COPY src src
RUN ./gradlew --no-daemon installDist

FROM eclipse-temurin:25.0.4_7-jre@sha256:bb036ed6cfdc57e3da7c22634d15f1b840d2caf76183861c80e81ca4b5104abb

RUN groupadd --system csp \
    && useradd --system --gid csp --home-dir /workspace --shell /usr/sbin/nologin csp \
    && mkdir -p /workspace \
    && chown csp:csp /workspace
WORKDIR /workspace
COPY --from=builder --chown=csp:csp /src/build/install/csp-demo-data /opt/csp-demo-data
USER csp

ENTRYPOINT ["/opt/csp-demo-data/bin/csp-demo-data"]
