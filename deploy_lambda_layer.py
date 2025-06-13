import os
import boto3
import argparse
import traceback
import configparser
import sys
from pathlib import Path
from botocore.exceptions import NoCredentialsError, ClientError, ProfileNotFound

def check_aws_credentials(profile=None):
    """
    Check if AWS credentials are properly configured
    
    Args:
        profile: AWS profile to use (default: None, which uses the default profile)
        
    Returns:
        bool: True if credentials are found, False otherwise
    """
    # Check environment variables first (highest precedence)
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        print("Found AWS credentials in environment variables.")
        return True
    
    # Check AWS credentials file
    aws_credentials_path = Path.home() / ".aws" / "credentials"
    aws_config_path = Path.home() / ".aws" / "config"
    
    # Dictionary to store available profiles
    available_profiles = {'credentials': [], 'config': []}
    has_credentials = False
    
    # Check credentials file
    if aws_credentials_path.exists():
        print(f"AWS credentials file found at {aws_credentials_path}")
        try:
            creds_config = configparser.ConfigParser()
            creds_config.read(aws_credentials_path)
            available_profiles['credentials'] = creds_config.sections()
            
            # Check if the specified profile exists
            if profile and profile in creds_config.sections():
                if 'aws_access_key_id' in creds_config[profile] and 'aws_secret_access_key' in creds_config[profile]:
                    print(f"Found credentials for profile '{profile}' in credentials file")
                    has_credentials = True
            # Check default profile if no profile specified
            elif not profile and 'default' in creds_config.sections():
                if 'aws_access_key_id' in creds_config['default'] and 'aws_secret_access_key' in creds_config['default']:
                    print(f"Found credentials for default profile in credentials file")
                    has_credentials = True
        except Exception as e:
            print(f"Error reading AWS credentials file: {str(e)}")
    
    # Check config file
    if aws_config_path.exists():
        print(f"AWS config file found at {aws_config_path}")
        try:
            config_parser = configparser.ConfigParser()
            config_parser.read(aws_config_path)
            
            # AWS config file uses "profile name" format except for default
            for section in config_parser.sections():
                section_name = section
                if section.startswith('profile '):
                    section_name = section[8:]  # Remove "profile " prefix
                available_profiles['config'].append(section_name)
                
            # Check for role assumption or similar credential methods
            target_profile = f"profile {profile}" if profile and profile != "default" else "default"
            
            if target_profile in config_parser.sections():
                section = config_parser[target_profile]
                # Check for common credential providers in config
                if any(key in section for key in ['credential_process', 'role_arn', 'credential_source', 'sso_start_url']):
                    print(f"Found credential provider in config file for profile '{profile or 'default'}'")
                    has_credentials = True
        except Exception as e:
            print(f"Error reading AWS config file: {str(e)}")
    
    # Try to validate credentials if we haven't confirmed yet
    if not has_credentials:
        print("Attempting to validate credentials with AWS STS...")
        try:
            # Fixed: Create a session first when using a profile
            if profile:
                session = boto3.Session(profile_name=profile)
                sts = session.client('sts')
            else:
                sts = boto3.client('sts')
                
            sts.get_caller_identity()
            print("Successfully validated credentials with AWS STS")
            return True
        except NoCredentialsError:
            print("No credentials found when validating with AWS STS")
        except ProfileNotFound as e:
            print(f"Profile error: {str(e)}")
        except Exception as e:
            print(f"Error validating credentials: {str(e)}")
            traceback.print_exc()
    
    # If we have credentials, return True
    if has_credentials:
        # For SSO profiles, provide specific instructions
        if profile and aws_config_path.exists():
            try:
                config_parser = configparser.ConfigParser()
                config_parser.read(aws_config_path)
                target_profile = f"profile {profile}"
                
                if target_profile in config_parser.sections():
                    section = config_parser[target_profile]
                    if 'sso_start_url' in section:
                        print(f"\nThis appears to be an SSO profile. You may need to run:")
                        print(f"aws sso login --profile {profile}")
                        print("before proceeding.\n")
            except Exception:
                pass
        return True
        
    # If we get here, we couldn't find valid credentials
    print("\n----- AWS CREDENTIAL CONFIGURATION HELP -----")
    print("AWS credentials not found or are incomplete. Please set up your credentials:")
    
    print("\n1. Using AWS CLI (Recommended):")
    print("   Run: aws configure")
    print("   You'll be prompted to enter your Access Key ID, Secret Access Key, default region, and output format")
    
    print("\n2. Manual Configuration:")
    print("   Create or edit ~/.aws/credentials with:")
    print("   [default]")
    print("   aws_access_key_id = YOUR_ACCESS_KEY")
    print("   aws_secret_access_key = YOUR_SECRET_KEY")
    print("   region = us-east-2")
    
    print("\n3. Environment Variables:")
    print("   Set: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables")
    
    # Print available profiles if any were found
    all_profiles = set(available_profiles['credentials'] + available_profiles['config'])
    if all_profiles:
        print("\nAvailable profiles found:")
        for p in sorted(all_profiles):
            profile_sources = []
            if p in available_profiles['credentials']:
                profile_sources.append("credentials")
            if p in available_profiles['config']:
                profile_sources.append("config")
            print(f"  - {p} (in {', '.join(profile_sources)})")
        
        print("\nTo use a specific profile:")
        print(f"  python {os.path.basename(__file__)} --profile PROFILE_NAME --zip {os.path.basename(args.zip if 'args' in locals() else 'layer.zip')}")
        
        # If it's an SSO profile, add specific instructions
        if profile and profile in available_profiles['config']:
            for section_name in config_parser.sections():
                if section_name == f"profile {profile}" and 'sso_start_url' in config_parser[section_name]:
                    print("\nFor SSO-based profile, first login with:")
                    print(f"  aws sso login --profile {profile}")
    
    print("\nFor more information, visit: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html")
    print("-----------------------------------------\n")
    return False

def deploy_lambda_layer(layer_name, layer_zip, region=None, profile=None):
    """
    Deploy a Lambda layer to AWS
    
    Args:
        layer_name: Name for the Lambda layer
        layer_zip: Path to the Lambda layer zip file
        region: AWS region to deploy to
        profile: AWS profile to use
        
    Returns:
        str: ARN of the deployed layer if successful, False otherwise
    """
    # Check if the layer zip exists
    if not os.path.exists(layer_zip):
        print(f"Error: Lambda layer zip not found at {layer_zip}")
        return False
    
    # Check AWS credentials before attempting deployment
    if not check_aws_credentials(profile):
        print("Error: AWS credentials are not properly configured.")
        return False
    
    try:
        # Create session with the specified profile
        if profile:
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            session = boto3.Session(region_name=region)
            
        # Create Lambda client
        lambda_client = session.client('lambda')
        
        # Test connectivity
        try:
            lambda_client.list_layers(MaxItems=1)
            print(f"Successfully connected to AWS Lambda service in region {region}")
        except ClientError as ce:
            if ce.response['Error']['Code'] in ['AccessDenied', 'UnauthorizedOperation']:
                print(f"Error: Your AWS credentials don't have permission to access Lambda in {region}.")
                print("Please check your IAM permissions and ensure you have Lambda access.")
                return False
            raise
        
        # Read the zip file content
        with open(layer_zip, 'rb') as zip_file:
            zip_content = zip_file.read()
        
        # Get file size for information
        file_size_mb = os.path.getsize(layer_zip) / (1024 * 1024)
        print(f"Uploading Lambda layer ({file_size_mb:.2f} MB)...")
        
        # Publish the layer
        response = lambda_client.publish_layer_version(
            LayerName=layer_name,
            Description=f'Python dependencies for video processing',
            Content={
                'ZipFile': zip_content
            },
            CompatibleRuntimes=['python3.8', 'python3.9', 'python3.10'],
            CompatibleArchitectures=['x86_64']
        )
        
        layer_version_arn = response['LayerVersionArn']
        print(f"Successfully published Lambda layer: {layer_version_arn}")
        
        # Print commands to attach the layer to your Lambda functions
        print("\nTo attach this layer to a Lambda function, use:")
        print(f"aws lambda update-function-configuration --function-name YOUR_FUNCTION_NAME --layers {layer_version_arn}")
        
        return layer_version_arn
    
    except NoCredentialsError:
        print("Error: AWS credentials not found.")
        print("Please configure your AWS credentials using one of the methods described above.")
        return False
    except ProfileNotFound:
        print(f"Error: AWS profile '{profile}' not found.")
        print("Please check your AWS configuration and ensure the profile exists.")
        return False
    except Exception as e:
        error_message = f"Error deploying Lambda layer: {str(e)}"
        error_details = traceback.format_exc()
        print(f"{error_message}\n{error_details}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy an AWS Lambda layer")
    parser.add_argument("--zip", help="Path to the Lambda layer zip file")
    parser.add_argument("--name", help="Name for the Lambda layer")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-2"), 
                        help="AWS region to deploy to (default: us-east-2 or AWS_REGION env var)")
    parser.add_argument("--profile", help="AWS profile to use")
    parser.add_argument("--check-only", action="store_true", 
                        help="Only check AWS credentials without deploying")
    
    args = parser.parse_args()
    
    if not args.zip:
        print("Error: Please provide the path to the Lambda layer zip file using --zip")
        sys.exit(1)
        
    if not args.name:
        args.name = os.path.basename(args.zip).replace(".zip", "")
    
    # Allow just checking credentials
    if args.check_only:
        if check_aws_credentials(args.profile):
            print("AWS credentials are properly configured.")
            sys.exit(0)
        else:
            sys.exit(1)
    
    # Deploy the Lambda layer
    deploy_lambda_layer(args.name, args.zip, args.region, args.profile)
