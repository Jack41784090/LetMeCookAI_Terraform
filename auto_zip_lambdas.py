#!/usr/bin/env python3
"""
Automatic Lambda Function Zipper

This script automatically zips all Python files in the src directory
and places them in the terraform/lambda_packages directory for deployment.
"""

import os
import zipfile
import shutil
from pathlib import Path

def create_lambda_zip(source_path, output_dir, zip_name):
    """
    Create a zip file for a Python file or directory.
    
    Args:
        source_path (Path): Path to the source file or directory
        output_dir (Path): Directory where the zip file will be created
        zip_name (str): Name of the zip file (without .zip extension)
    """
    zip_path = output_dir / f"{zip_name}.zip"
    
    # Remove existing zip file if it exists
    if zip_path.exists():
        zip_path.unlink()
        print(f"Removed existing {zip_path.name}")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if source_path.is_file():
            # Single Python file
            zipf.write(source_path, source_path.name)
            print(f"Added {source_path.name} to {zip_name}.zip")
        elif source_path.is_dir():
            # Directory with Python files
            for file_path in source_path.rglob("*.py"):
                # Skip files in .venv directories
                if ".venv" in file_path.parts:
                    continue
                # Calculate the relative path within the directory
                arcname = file_path.relative_to(source_path)
                zipf.write(file_path, arcname)
                print(f"Added {arcname} to {zip_name}.zip")
            
            # Also include requirements.txt if it exists
            requirements_file = source_path / "requirements.txt"
            if requirements_file.exists():
                zipf.write(requirements_file, "requirements.txt")
                print(f"Added requirements.txt to {zip_name}.zip")

    print(f"Created {zip_path}")

def create_lambda_layer_zip(source_dir, output_dir, layer_name):
    """
    Create a lambda layer zip with proper directory structure.
    
    Args:
        source_dir (Path): Directory containing the Python code
        output_dir (Path): Directory where the zip file will be created
        layer_name (str): Name of the layer zip file
    """
    zip_path = output_dir / f"lambda-layer-{layer_name}.zip"
    
    # Remove existing zip file if it exists
    if zip_path.exists():
        zip_path.unlink()
        print(f"Removed existing {zip_path.name}")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Lambda layers need python/ directory structure
        for file_path in source_dir.rglob("*.py"):
            # Skip files in .venv directories
            if ".venv" in file_path.parts:
                continue
            # Create the lambda layer structure: python/
            arcname = Path("python") / file_path.relative_to(source_dir)
            zipf.write(file_path, arcname)
            print(f"Added {arcname} to lambda-layer-{layer_name}.zip")

        # Include requirements.txt in the layer if it exists
        requirements_file = source_dir / "requirements.txt"
        if requirements_file.exists():
            zipf.write(requirements_file, "python/requirements.txt")
            print(f"Added python/requirements.txt to lambda-layer-{layer_name}.zip")

    print(f"Created {zip_path}")

def main():
    """Main function to zip all Python files for Lambda deployment."""
    
    # Define paths
    project_root = Path(__file__).parent
    src_dir = project_root / "src"
    output_dir = project_root / "terraform" / "lambda_packages"
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("Starting automatic Lambda function zipping...")
    print(f"Source directory: {src_dir}")
    print(f"Output directory: {output_dir}")
    print("-" * 50)
      # Process all items in src directory
    for item in src_dir.iterdir():
        if item.is_file() and item.suffix == ".py":
            # Single Python file
            zip_name = item.stem  # filename without extension
            create_lambda_zip(item, output_dir, zip_name)
            
        elif item.is_dir() and item.name != ".venv" and any(item.rglob("*.py")):
            # Directory containing Python files (excluding .venv)
            dir_name = item.name
            
            # Create both regular lambda zip and layer zip
            create_lambda_zip(item, output_dir, dir_name)
            create_lambda_layer_zip(item, output_dir, dir_name)
    
    print("-" * 50)
    print("Lambda function zipping completed!")
    
    # List all created zip files
    zip_files = list(output_dir.glob("*.zip"))
    if zip_files:
        print(f"\nCreated {len(zip_files)} zip files:")
        for zip_file in sorted(zip_files):
            size_mb = zip_file.stat().st_size / (1024 * 1024)
            print(f"  - {zip_file.name} ({size_mb:.2f} MB)")
    else:
        print("\nNo zip files were created.")

if __name__ == "__main__":
    main()
