# RAHBAR chat UI: static files served by unprivileged nginx on 8080. Build context: ui/
# nginx.conf writes only under /tmp, so the Deployment mounts an emptyDir there and runs
# with a read-only root filesystem.
FROM nginxinc/nginx-unprivileged:1.27.5-alpine

# Security fixes for the base image's Alpine packages (Trivy fails on fixable HIGH/CRITICAL).
# The image runs as uid 101, so switch to root only for the upgrade.
USER root
RUN apk upgrade --no-cache

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
