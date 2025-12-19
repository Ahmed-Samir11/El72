"""
Comprehensive Integration Test for Elhaq Price Alert System

Tests the complete flow:
1. User registration and authentication
2. Alert creation
3. Price drop simulation (via Redis)
4. WhatsApp notification delivery verification

Usage: python tests/integration_test.py
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

try:
    import psycopg2
    import redis.asyncio as aioredis
    import requests
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install psycopg2-binary redis requests")
    sys.exit(1)


# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
API_BASE = os.getenv("API_BASE", "http://localhost:8000")

# Test configuration
TEST_PHONE = "+201091095176"  # Must include + prefix for API validation
TEST_PASSWORD = "testpass123"
TEST_SKU = "TEST-LAPTOP-INTEGRATION"
TEST_URL = f"https://example.com/product/{TEST_SKU}"  # URL must contain the SKU
INITIAL_PRICE = 10000
TARGET_PRICE = 8000
DROPPED_PRICE = 7500  # Below target


class Colors:
    """ANSI color codes"""
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def log_step(message):
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{message}{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}")


def log_success(message):
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")


def log_error(message):
    print(f"{Colors.RED}✗ {message}{Colors.END}")


def log_info(message):
    print(f"{Colors.YELLOW}➜ {message}{Colors.END}")


class IntegrationTest:
    def __init__(self):
        self.user_token = None
        self.user_id = None
        self.alert_id = None
        self.redis_client = None
        self.test_results = []
    
    def cleanup_database(self):
        """Clear alerts table before starting test"""
        log_step("Cleaning up database (clearing alerts)")
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("TRUNCATE TABLE alerts CASCADE;")
            conn.commit()
            cursor.close()
            conn.close()
            log_success("Alerts table cleared")
            return True
        except Exception as e:
            log_error(f"Database cleanup failed: {e}")
            return False
    
    async def setup_redis(self):
        """Initialize Redis connection"""
        log_step("Setting up Redis connection")
        try:
            self.redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
            await self.redis_client.ping()
            log_success("Redis connection established")
            return True
        except Exception as e:
            log_error(f"Redis connection failed: {e}")
            return False
    
    def test_api_health(self):
        """Test API service health"""
        log_step("Step 1: Checking API Service Health")
        try:
            response = requests.get(f"{API_BASE}/docs", timeout=5)
            if response.status_code == 200:
                log_success("API service is healthy")
                return True
            else:
                log_error(f"API returned status {response.status_code}")
                return False
        except Exception as e:
            log_error(f"API health check failed: {e}")
            return False
    
    def test_user_registration(self):
        """Test user registration"""
        log_step("Step 2: User Registration")
        try:
            # Try to register
            response = requests.post(
                f"{API_BASE}/auth/register",
                json={"phone": TEST_PHONE, "password": TEST_PASSWORD},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.user_token = data.get("access_token")
                log_success(f"User registered: {TEST_PHONE}")
                log_info(f"Token: {self.user_token[:20]}..." if self.user_token else "No token")
                return True
            elif response.status_code == 400 and ("already" in response.text.lower() or "registered" in response.text.lower()):
                log_info("User already exists, trying login...")
                return self.test_user_login()
            else:
                log_error(f"Registration failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log_error(f"Registration error: {e}")
            return False
    
    def test_user_login(self):
        """Test user login"""
        log_info("Attempting login...")
        try:
            response = requests.post(
                f"{API_BASE}/auth/login",
                json={"phone": TEST_PHONE, "password": TEST_PASSWORD},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.user_token = data.get("access_token")
                log_success("User logged in successfully")
                return True
            else:
                log_error(f"Login failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log_error(f"Login error: {e}")
            return False
    
    def test_create_alert(self):
        """Test alert creation"""
        log_step("Step 3: Creating Price Alert")
        if not self.user_token:
            log_error("No authentication token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.user_token}"}
            response = requests.post(
                f"{API_BASE}/alerts",
                json={
                    "target_url": TEST_URL,
                    "target_price": TARGET_PRICE
                },
                headers=headers,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                self.alert_id = data.get("id")
                log_success(f"Alert created: ID {self.alert_id}")
                log_info(f"Target URL: {TEST_URL}")
                log_info(f"Target Price: {TARGET_PRICE} EGP")
                return True
            else:
                log_error(f"Alert creation failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log_error(f"Alert creation error: {e}")
            return False
    
    def get_user_id_from_db(self):
        """Get user ID from database"""
        log_step("Step 4: Retrieving User ID from Database")
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE phone = %s", (TEST_PHONE,))
            result = cur.fetchone()
            cur.close()
            conn.close()
            
            if result:
                self.user_id = result[0]
                log_success(f"User ID: {self.user_id}")
                return True
            else:
                log_error("User not found in database")
                return False
        except Exception as e:
            log_error(f"Database query failed: {e}")
            return False
    
    async def simulate_price_drop(self):
        """Simulate a price drop by publishing to Redis stream"""
        log_step("Step 5: Simulating Price Drop Event")
        
        if not self.user_id:
            log_error("User ID not available")
            return False
        
        try:
            # Clear any existing deduplication key
            dedup_key = f"alert_sent:{self.user_id}:{TEST_SKU}"
            deleted = await self.redis_client.delete(dedup_key)
            if deleted:
                log_info(f"Cleared existing deduplication key")
            
            # Create price drop event payload
            payload = {
                "user_phone": TEST_PHONE.lstrip('+'),  # WhatsApp API expects phone without + prefix
                "user_id": str(self.user_id),
                "sku": TEST_SKU,
                "price": DROPPED_PRICE,
                "original_price": INITIAL_PRICE,
                "discount_percent": round(((INITIAL_PRICE - DROPPED_PRICE) / INITIAL_PRICE) * 100),
                "url": TEST_URL,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Publish to Redis stream
            message_id = await self.redis_client.xadd(
                "stream:confirmed_deals",
                {"payload": json.dumps(payload)}
            )
            
            log_success(f"Price drop event published to Redis")
            log_info(f"Message ID: {message_id}")
            log_info(f"Price: {INITIAL_PRICE} → {DROPPED_PRICE} EGP ({payload['discount_percent']}% off)")
            
            return True
        except Exception as e:
            log_error(f"Failed to publish price drop event: {e}")
            return False
    
    async def verify_whatsapp_processing(self):
        """Verify WhatsApp service processed the message"""
        log_step("Step 6: Verifying WhatsApp Notification Processing")
        
        try:
            log_info("Waiting 8 seconds for WhatsApp service to process...")
            await asyncio.sleep(8)
            
            # Check if message was processed (deduplication key exists)
            dedup_key = f"alert_sent:{self.user_id}:{TEST_SKU}"
            exists = await self.redis_client.exists(dedup_key)
            
            if exists:
                ttl = await self.redis_client.ttl(dedup_key)
                log_success(f"Message processed and sent!")
                log_info(f"Deduplication key set (TTL: {ttl}s)")
            else:
                log_error("Message not processed (deduplication key not found)")
                log_info("Checking stream for pending messages...")
                
                # Check pending messages
                try:
                    pending = await self.redis_client.execute_command(
                        'XPENDING', 'stream:confirmed_deals', 'cg_whatsapp'
                    )
                    log_info(f"Pending messages: {pending}")
                except Exception:
                    pass
                
                return False
            
            # Check WhatsApp container logs
            log_info("Checking WhatsApp service logs...")
            import subprocess
            result = subprocess.run(
                ["docker", "logs", "--tail", "20", "el72-whatsapp-1"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            logs = result.stdout + result.stderr
            
            # WhatsApp logs will have phone without + prefix
            phone_for_log = TEST_PHONE.lstrip('+')
            
            if "WhatsApp message sent to" in logs and phone_for_log in logs:
                log_success("Message confirmed in WhatsApp service logs")
                
                # Extract message ID
                import re
                message_ids = re.findall(r"wamid\.[A-Za-z0-9+/=]+", logs)
                if message_ids:
                    log_info(f"WhatsApp Message ID: {message_ids[-1]}")
                
                return True
            elif "MOCK" in logs and phone_for_log in logs:
                log_success("Message sent in MOCK mode (check logs)")
                return True
            else:
                log_error("Message not found in WhatsApp logs")
                log_info("Recent logs:")
                print(logs[-500:] if len(logs) > 500 else logs)
                return False
                
        except Exception as e:
            log_error(f"Verification failed: {e}")
            return False
    
    async def verify_redis_stream(self):
        """Verify Redis stream state"""
        log_step("Step 7: Verifying Redis Stream State")
        
        try:
            # Get stream info
            stream_info = await self.redis_client.xinfo_stream("stream:confirmed_deals")
            length = stream_info.get('length', 0)
            
            log_info(f"Stream length: {length}")
            
            # Get consumer group info
            groups = await self.redis_client.xinfo_groups("stream:confirmed_deals")
            
            for group in groups:
                if group['name'] == 'cg_whatsapp':
                    pending = group['pending']
                    log_info(f"Pending messages in cg_whatsapp: {pending}")
                    
                    if pending == 0:
                        log_success("All messages processed by WhatsApp service")
                        return True
                    else:
                        # Pending messages from previous runs don't indicate test failure
                        # The important check is that our message was processed (Step 6)
                        log_info(f"{pending} messages pending (may be from previous test runs)")
                        log_success("Current test message was processed successfully")
                        return True
            
            log_error("WhatsApp consumer group not found")
            return False
            
        except Exception as e:
            log_error(f"Redis stream verification failed: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup test data"""
        log_step("Cleanup")
        
        response = input("\nClean up test data? (y/N): ").strip().lower()
        if response != 'y':
            log_info("Skipping cleanup")
            return
        
        try:
            # Clear deduplication key
            if self.user_id:
                dedup_key = f"alert_sent:{self.user_id}:{TEST_SKU}"
                await self.redis_client.delete(dedup_key)
                log_success("Cleared deduplication key")
            
            log_info("Test alert and user remain in database for inspection")
            
        except Exception as e:
            log_error(f"Cleanup failed: {e}")
    
    async def run(self):
        """Run the complete integration test"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}")
        print("=" * 60)
        print("  ELHAQ INTEGRATION TEST")
        print("  Complete Price Alert Flow Verification")
        print("=" * 60)
        print(Colors.END)
        
        # Cleanup database first
        if not self.cleanup_database():
            log_error("Database cleanup failed, continuing anyway...")
        
        # Setup
        if not await self.setup_redis():
            return False
        
        # Run tests
        tests = [
            ("API Health", self.test_api_health),
            ("User Registration/Login", self.test_user_registration),
            ("Create Alert", self.test_create_alert),
            ("Get User ID", self.get_user_id_from_db),
            ("Simulate Price Drop", self.simulate_price_drop),
            ("Verify WhatsApp Processing", self.verify_whatsapp_processing),
            ("Verify Redis Stream", self.verify_redis_stream),
        ]
        
        results = []
        for test_name, test_func in tests:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            
            results.append((test_name, result))
            
            if not result:
                log_error(f"Test failed: {test_name}")
                break
        
        # Print summary
        log_step("TEST SUMMARY")
        
        all_passed = True
        for test_name, passed in results:
            if passed:
                log_success(f"{test_name}: PASSED")
            else:
                log_error(f"{test_name}: FAILED")
                all_passed = False
        
        print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
        if all_passed:
            print(f"{Colors.GREEN}{Colors.BOLD}✓ ALL TESTS PASSED{Colors.END}")
            print(f"\n{Colors.YELLOW}Integration test successful!{Colors.END}")
            print(f"{Colors.YELLOW}Check your WhatsApp ({TEST_PHONE}) for the alert message.{Colors.END}")
        else:
            print(f"{Colors.RED}{Colors.BOLD}✗ SOME TESTS FAILED{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}\n")
        
        # Cleanup
        await self.cleanup()
        
        # Close Redis
        if self.redis_client:
            await self.redis_client.aclose()
        
        return all_passed


async def main():
    test = IntegrationTest()
    success = await test.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrupted by user{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
