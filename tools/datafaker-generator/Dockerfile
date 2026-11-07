FROM eclipse-temurin:25.0.5_8-jdk@sha256:83f4a7fc27df94dcc7b8de04d14cbbba8da14406f921e966969c3b09000aa507 AS builder

WORKDIR /src

COPY gradle gradle
COPY gradlew gradlew.bat settings.gradle.kts build.gradle.kts ./
RUN ./gradlew --no-daemon dependencies >/dev/null

COPY src src
RUN ./gradlew --no-daemon installDist

FROM eclipse-temurin:25.0.5_8-jre@sha256:ecdc0adb37bde1a281c4d245a3cd535004b1fc8322d560f5b09463b248c81df0

RUN groupadd --system csp \
    && useradd --system --gid csp --home-dir /workspace --shell /usr/sbin/nologin csp \
    && mkdir -p /workspace \
    && chown csp:csp /workspace
WORKDIR /workspace
COPY --from=builder --chown=csp:csp /src/build/install/csp-demo-data /opt/csp-demo-data
USER csp

ENTRYPOINT ["/opt/csp-demo-data/bin/csp-demo-data"]
