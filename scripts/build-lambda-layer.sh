#!/bin/bash
set -e

# Build script for AWS Lambda Python dependencies layer
# Uses poetry.lock to ensure exact same versions as local development

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
LAYER_DIR="$PROJECT_ROOT/build/lambda-layer"

echo "Building Lambda Layer for Python dependencies..."
echo "   Project root: $PROJECT_ROOT"

# Clean previous build
if [ -d "$LAYER_DIR" ]; then
    echo "   Cleaning previous build..."
    rm -rf "$LAYER_DIR"
fi

# Create layer directory structure
mkdir -p "$LAYER_DIR/python"

# Export pinned dependencies from poetry.lock
echo "   Exporting dependencies from poetry.lock..."
REQUIREMENTS_FILE="$PROJECT_ROOT/build/requirements.txt"
poetry export -f requirements.txt --without-hashes -o "$REQUIREMENTS_FILE"

# Install dependencies for Lambda (Linux x86_64)
echo "   Installing dependencies for Lambda..."
pip install \
    --target "$LAYER_DIR/python" \
    --platform manylinux2014_x86_64 \
    --python-version 3.11 \
    --only-binary=:all: \
    -r "$REQUIREMENTS_FILE"

# Create zip
echo "   Creating layer zip..."
cd "$LAYER_DIR"
zip -r "$PROJECT_ROOT/build/python-deps.zip" python/ > /dev/null

# Display size
SIZE=$(du -h "$PROJECT_ROOT/build/python-deps.zip" | cut -f1)
echo "   Layer built successfully: build/python-deps.zip ($SIZE)"

# Upload to S3 if bucket name provided
if [ -n "$1" ]; then
    BUCKET_NAME="$1"
    echo ""
    echo "   Uploading to S3..."
    aws s3 cp "$PROJECT_ROOT/build/python-deps.zip" "s3://$BUCKET_NAME/layers/python-deps.zip"
    echo "   Uploaded to s3://$BUCKET_NAME/layers/python-deps.zip"
else
    echo ""
    echo "   To upload to S3, run:"
    echo "   aws s3 cp build/python-deps.zip s3://YOUR-BUCKET/layers/python-deps.zip"
fi

echo ""
echo "Done!"
