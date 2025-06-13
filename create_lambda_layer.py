import os
import sys
import shutil
import subprocess
import platform
import argparse
import glob

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
        if any(glob.fnmatch.fnmatch(item, pattern) for pattern in excluded_patterns):
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create AWS Lambda layer from virtual environment")
    parser.add_argument("--venv", help="Path to virtual environment directory")
    parser.add_argument("--output", help="Name for the output zip file")
    parser.add_argument("--all", action="store_true", help="Create layers for all found virtual environments")
    
    args = parser.parse_args()
    
    if args.all:
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
        create_lambda_layer(args.venv, args.output)
