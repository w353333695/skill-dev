#TODO: chose a builder image
#FROM docker.easyops.local/ci/pkgbuild:1.0.0 AS build
FROM docker.easyops.local/ci/pkgbuild_golang:3.0.0 AS build

ARG CI_WORKSPACE=/workspace/src/
ARG PLUGIN_APP_NAME=fintech_data
COPY . /workspace/src/

#Build
RUN set -eux; \
    /bin/pkgbuild

#Install
RUN set -eux; \
    mkdir -p /usr/local/easyops/${PLUGIN_APP_NAME}; \
    cp /workspace/src/.docker/${PLUGIN_APP_NAME}/entrypoint.sh /usr/local/easyops/${PLUGIN_APP_NAME}/entrypoint.sh; \
    chmod a+x /usr/local/easyops/${PLUGIN_APP_NAME}/entrypoint.sh; \
    source /workspace/src/.pipeline_env_var; \
    tar -zxvf ${artifact_file} -C /usr/local/easyops/${PLUGIN_APP_NAME}

#Build Image
#TODO: chose a base image
#FROM docker.easyops.local/library/base:4-python27-buster
#FROM docker.easyops.local/library/base:4-php72-nginx-buster
FROM docker.easyops.local/library/base:4-generic-buster

WORKDIR /usr/local/easyops/fintech_data
COPY --from=build /usr/local/easyops/fintech_data /usr/local/easyops/fintech_data/

#TODO: add install post script

ENTRYPOINT ["./entrypoint.sh"]