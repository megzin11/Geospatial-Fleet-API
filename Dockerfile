# Use a lightweight Python image to simulate resource-constrained edge devices
FROM python:3.15-slim

# Set the working directory inside the container
WORKDIR /edge_node

# Copy requirements first to leverage Docker layer caching
COPY ./requirements.txt /edge_node/requirements.txt

# Install dependencies without storing cache to keep the image size minimal
RUN pip install --no-cache-dir --upgrade -r /edge_node/requirements.txt

# Copy the actual application code
COPY ./app /edge_node/app

# Expose the port Uvicorn will broadcast on
EXPOSE 8000

# Command to run the high-performance API server
CMD ["uvicorn", "app.main:api", "--host", "0.0.0.0", "--port", "8000"]