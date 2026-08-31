# DATA 260 - Homework 1
# Serves the static recall-notice web application with Nginx.
# Build context is code/web_application/ so only the front-end files are copied.

# Start from a small official Nginx image (Alpine Linux base, ~10 MB).
FROM nginx:alpine

# Remove the default Nginx welcome page.
RUN rm -rf /usr/share/nginx/html/*

# Copy the build context (index.html, app.js) into the Nginx web root.
COPY . /usr/share/nginx/html/

# Document that the container serves HTTP on port 80.
EXPOSE 80

# Run Nginx in the foreground so the container stays alive.
CMD ["nginx", "-g", "daemon off;"]
