import os
import sys
import shutil
import subprocess
import platform
import argparse
import glob
import tempfile
import fnmatch

def find_requirements_files(src_dir):
    """
    Find all requirements.txt files in the src directory
    """
    requirements_files = []
    
    for root, dirs, files in os.walk(src_dir):
        if 'requirements.txt' in files:
            requirements_path = os.path.join(root, 'requirements.txt')
            parent_folder = os.path.basename(root)
            requirements_files.append((requirements_path, parent_folder))
    
    return requirements_files

def find_venv_paths(base_dir):
    """
    Find all virtual environment paths in the project
    """
    venv_paths = []
    
    # Look for .venv directories
    for root, dirs, _ in os.walk(base_dir):
        if '.venv' in dirs:
            venv_paths.append(os.path.join(root, '.venv'))
    
    return venv_paths

def create_lambda_layer(venv_path=None, output_name=None):
    """
    Create an AWS Lambda layer from a specific virtual environment's packages.
    
    Args:
        venv_path: Path to the virtual environment directory
        output_name: Name for the output zip file
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # If no venv path specified, use current directory's .venv or search for venvs
    if not venv_path:
        default_venv = os.path.join(base_dir, '.venv')
        if os.path.exists(default_venv):
            venv_path = default_venv
        else:
            venv_paths = find_venv_paths(base_dir)
            if venv_paths:
                print("Multiple virtual environments found:")
                for i, path in enumerate(venv_paths):
                    relative_path = os.path.relpath(path, base_dir)
                    print(f"[{i+1}] {relative_path}")
                
                selection = int(input("Select virtual environment (number): ")) - 1
                if 0 <= selection < len(venv_paths):
                    venv_path = venv_paths[selection]
                else:
                    print("Invalid selection")
                    return False
            else:
                print("No virtual environments found")
                return False
    
    # Determine component name from venv path for naming the layer
    component_name = os.path.basename(os.path.dirname(venv_path))
    if not output_name:
        output_name = f"lambda-layer-{component_name}"

    # Get Python version
    try:
        # Try to get Python version from the venv
        if platform.system() == "Windows":
            python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            python_exe = os.path.join(venv_path, "bin", "python")
            
        if os.path.exists(python_exe):
            result = subprocess.run([python_exe, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], 
                                    capture_output=True, text=True)
            python_version = result.stdout.strip()
        else:
            # Fallback to current Python version
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    except:
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        
    print(f"Creating Lambda layer for {python_version} from {venv_path}")
    
    # Create directories for Lambda layer
    layer_dir = os.path.join(base_dir, f"{output_name}")
    python_lib_dir = os.path.join(layer_dir, "python", "lib", f"python{python_version}", "site-packages")
    os.makedirs(python_lib_dir, exist_ok=True)
    
    # Get site-packages directory from the specified virtualenv
    if platform.system() == "Windows":
        site_packages_dir = os.path.join(venv_path, "Lib", "site-packages")
    else:
        site_packages_dir = os.path.join(venv_path, "lib", f"python{python_version}", "site-packages")
    
    if not os.path.exists(site_packages_dir):
        print(f"Error: Site packages directory not found at {site_packages_dir}")
        return False
    
    # Copy packages to the layer directory
    print(f"Copying packages from {site_packages_dir}...")
    
    # Create a list of excluded patterns
    excluded_patterns = [
        '*.pyc', 
        '*.pyo', 
        '__pycache__', 
        '*.dist-info',
        '*.egg-info',
        'pip',
        'setuptools',
        'wheel',
        'pkg_resources',
        'easy_install.py'
    ]
    
    # Lambda-specific package adjustments
    package_adjustments = {
        'opencv_python': 'opencv-python-headless',  # Replace with headless version for Lambda
        'cv2': None  # Will be provided by opencv-python-headless
    }
    
    # Copy packages with exclusions
    for item in os.listdir(site_packages_dir):
        src_path = os.path.join(site_packages_dir, item)
          # Skip if item matches excluded patterns
        if any(fnmatch.fnmatch(item, pattern) for pattern in excluded_patterns):
            continue
            
        # Handle package adjustments
        if item in package_adjustments:
            if package_adjustments[item] is None:
                continue  # Skip this package
            else:
                # Handle package replacement (would need pip install)
                print(f"Note: {item} should be replaced with {package_adjustments[item]} for Lambda")
        
        dest_path = os.path.join(python_lib_dir, item)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dest_path, ignore=shutil.ignore_patterns(*excluded_patterns))
        else:
            shutil.copy2(src_path, dest_path)
    
    # Create zip file for Lambda layer
    print("Creating zip file...")
    zip_path = os.path.join(base_dir, f"{output_name}.zip")
    shutil.make_archive(
        os.path.join(base_dir, output_name),
        'zip',
        layer_dir
    )
    
    # Clean up the temp directory
    shutil.rmtree(layer_dir)
    
    print(f"Lambda layer zip created at: {os.path.abspath(zip_path)}")
    print("You can now upload this zip file as a Lambda layer in the AWS Console or using the AWS CLI.")
    
    return zip_path

def create_lambda_layer_from_requirements(requirements_path, parent_folder, base_dir):
    """
    Create an AWS Lambda layer by installing packages from requirements.txt
    
    Args:
        requirements_path: Path to the requirements.txt file
        parent_folder: Name of the parent folder containing requirements.txt
        base_dir: Base directory for output
    """
    output_name = f"lambda-layer-{parent_folder}"
    
    # Get Python version
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"Creating Lambda layer '{output_name}' from {requirements_path}")
    
    # Create temporary directory for package installation
    with tempfile.TemporaryDirectory() as temp_dir:
        # Install packages to temporary directory
        temp_site_packages = os.path.join(temp_dir, "site-packages")
        
        print(f"Installing packages from {requirements_path}...")
        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install", 
                "-r", requirements_path, 
                "-t", temp_site_packages
            ], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error installing packages: {e}")
            return False
        
        # Create directories for Lambda layer
        layer_dir = os.path.join(base_dir, f"{output_name}")
        python_lib_dir = os.path.join(layer_dir, "python", "lib", f"python{python_version}", "site-packages")
        os.makedirs(python_lib_dir, exist_ok=True)
        
        # Create a list of excluded patterns
        excluded_patterns = [
            '*.pyc', 
            '*.pyo', 
            '__pycache__', 
            '*.dist-info',
            '*.egg-info',
            'pip*',
            'setuptools*',
            'wheel*',
            'pkg_resources*',
            'easy_install.py'
        ]
        
        # Copy packages to the layer directory
        print(f"Copying packages to layer directory...")
        
        for item in os.listdir(temp_site_packages):
            src_path = os.path.join(temp_site_packages, item)
            
            # Skip if item matches excluded patterns
            if any(fnmatch.fnmatch(item, pattern) for pattern in excluded_patterns):
                continue
            
            dest_path = os.path.join(python_lib_dir, item)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path, ignore=shutil.ignore_patterns(*excluded_patterns))
            else:
                shutil.copy2(src_path, dest_path)
        
        # Create zip file for Lambda layer in lambda_packages directory
        lambda_packages_dir = os.path.join(base_dir, "terraform", "lambda_packages")
        os.makedirs(lambda_packages_dir, exist_ok=True)
        
        print("Creating zip file...")
        zip_path = os.path.join(lambda_packages_dir, f"{output_name}.zip")
        shutil.make_archive(
            os.path.join(lambda_packages_dir, output_name),
            'zip',
            layer_dir
        )
        
        # Clean up the temp layer directory
        shutil.rmtree(layer_dir)
        
        print(f"Lambda layer zip created at: {os.path.abspath(zip_path)}")
        return zip_path

def process_all_requirements():
    """
    Process all requirements.txt files found in the src directory
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(base_dir, "src")
    
    if not os.path.exists(src_dir):
        print("Error: src directory not found")
        return False
    
    requirements_files = find_requirements_files(src_dir)
    
    if not requirements_files:
        print("No requirements.txt files found in src directory")
        return False
    
    print(f"Found {len(requirements_files)} requirements.txt file(s):")
    for req_path, parent_folder in requirements_files:
        print(f"  - {parent_folder}: {req_path}")
    
    success_count = 0
    for req_path, parent_folder in requirements_files:
        try:
            if create_lambda_layer_from_requirements(req_path, parent_folder, base_dir):
                success_count += 1
        except Exception as e:
            print(f"Error processing {parent_folder}: {e}")
    
    print(f"\nSuccessfully created {success_count} out of {len(requirements_files)} lambda layers")
    return success_count > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create AWS Lambda layers from virtual environments or requirements.txt files")
    parser.add_argument("--venv", help="Path to virtual environment directory")
    parser.add_argument("--output", help="Name for the output zip file")
    parser.add_argument("--all", action="store_true", help="Create layers for all found virtual environments")
    parser.add_argument("--requirements", action="store_true", help="Process all requirements.txt files in src directory")
    
    args = parser.parse_args()
    
    if args.requirements:
        # Process all requirements.txt files in src directory
        process_all_requirements()
    elif args.all:
        # Create layers for all virtual environments
        base_dir = os.path.dirname(os.path.abspath(__file__))
        venv_paths = find_venv_paths(base_dir)
        
        if not venv_paths:
            print("No virtual environments found")
        else:
            for venv_path in venv_paths:
                component_name = os.path.basename(os.path.dirname(venv_path))
                output_name = f"lambda-layer-{component_name}"
                print(f"\nProcessing {component_name}...")
                create_lambda_layer(venv_path, output_name)
    else:
        if not args.venv and not args.output:
            # Default behavior: process requirements.txt files
            print("No specific arguments provided. Processing requirements.txt files in src directory...")
            process_all_requirements()
        else:
            create_lambda_layer(args.venv, args.output)
