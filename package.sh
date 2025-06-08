#!/bin/bash
# Package Lambda functions for Terraform deployment

set -e

echo "LetMeCookAI Lambda Function Packager"
echo "===================================="
echo ""

echo "Packaging Lambda functions for deployment..."

# Create deployment directory if it doesn't exist
mkdir -p terraform/lambda_packages

# List of Lambda functions to package
FUNCTIONS=("auth_validator" "request_processor" "status_retriever")

for func in "${FUNCTIONS[@]}"; do
    echo "Packaging $func..."
    
    # Create temporary directory for this function
    temp_dir=$(mktemp -d)
    
    # Copy Python file to temp directory
    if [ -f "src/$func.py" ]; then
        cp "src/$func.py" "$temp_dir/"
        
        # Create ZIP file
        cd "$temp_dir"
        zip -r "../../../terraform/lambda_packages/$func.zip" .
        cd - > /dev/null
        
        # Clean up temp directory
        rm -rf "$temp_dir"
        
        echo "✓ Created terraform/lambda_packages/$func.zip"
    else
        echo "✗ Warning: src/$func.py not found"
    fi
done

echo ""
echo "Packaging complete!"
echo "Lambda packages are ready in terraform/lambda_packages/"
