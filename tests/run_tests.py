#!/usr/bin/env python3
"""
Test Suite Runner for MCP Agent System
Runs all test categories with comprehensive reporting
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple


class TestRunner:
    """Manages and runs all test suites"""
    
    def __init__(self):
        self.test_files = {
            "Basic Tests": "test_basic.py",
            "Comprehensive Tests": "test_comprehensive.py", 
            "HTTP Transport Tests": "test_http.py",
            "Performance Tests": "test_performance.py",
        }
        self.results: Dict[str, Tuple[bool, float, str]] = {}
    
    async def run_test_file(self, test_name: str, test_file: str) -> Tuple[bool, float, str]:
        """Run a single test file and return (success, duration, output)"""
        print(f"\n{'='*60}")
        print(f"🧪 Running {test_name}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        try:
            # Run the test file
            process = await asyncio.create_subprocess_exec(
                sys.executable, test_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd()
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode('utf-8')
            
            end_time = time.time()
            duration = end_time - start_time
            
            success = process.returncode == 0
            
            # Print the output
            print(output)
            
            if success:
                print(f"✅ {test_name} completed successfully in {duration:.2f}s")
            else:
                print(f"❌ {test_name} failed after {duration:.2f}s")
            
            return success, duration, output
            
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            error_msg = f"Exception running {test_name}: {e}"
            print(f"❌ {error_msg}")
            return False, duration, error_msg
    
    async def run_all_tests(self, skip_performance: bool = False, skip_http: bool = False):
        """Run all test suites"""
        print("🚀 Starting Complete MCP Agent Test Suite")
        print("=" * 80)
        
        total_start = time.time()
        
        for test_name, test_file in self.test_files.items():
            # Skip options for faster testing
            if skip_performance and "Performance" in test_name:
                print(f"⏭️  Skipping {test_name} (--skip-performance)")
                continue
            if skip_http and "HTTP" in test_name:
                print(f"⏭️  Skipping {test_name} (--skip-http)")
                continue
            
            # Check if test file exists
            if not Path(test_file).exists():
                print(f"⚠️  {test_name} file not found: {test_file}")
                self.results[test_name] = (False, 0, f"File not found: {test_file}")
                continue
            
            success, duration, output = await self.run_test_file(test_name, test_file)
            self.results[test_name] = (success, duration, output)
        
        total_end = time.time()
        total_duration = total_end - total_start
        
        self.print_summary(total_duration)
    
    def print_summary(self, total_duration: float):
        """Print comprehensive test summary"""
        print("\n" + "=" * 80)
        print("🎯 COMPLETE TEST SUITE SUMMARY")
        print("=" * 80)
        
        passed = 0
        failed = 0
        total_test_time = 0
        
        for test_name, (success, duration, _) in self.results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status:<8} {test_name:<25} ({duration:.2f}s)")
            if success:
                passed += 1
            else:
                failed += 1
            total_test_time += duration
        
        print("-" * 80)
        print(f"Total Tests Run:     {len(self.results)}")
        print(f"Passed:              {passed}")
        print(f"Failed:              {failed}")
        print(f"Success Rate:        {(passed/len(self.results)*100):.1f}%" if self.results else "N/A")
        print(f"Total Test Time:     {total_test_time:.2f}s")
        print(f"Total Runtime:       {total_duration:.2f}s")
        
        if failed == 0:
            print("\n🎉 ALL TESTS PASSED! Your MCP Agent system is working correctly.")
        else:
            print(f"\n⚠️  {failed} test suite(s) failed. Check the output above for details.")
            
        # Recommendations based on results
        print("\n📋 TEST COVERAGE RECOMMENDATIONS:")
        
        if len(self.results) >= 4:
            print("✅ Comprehensive test coverage achieved")
        else:
            print("⚠️  Consider adding more test categories")
            
        if any("Basic" in name and success for name, (success, _, _) in self.results.items()):
            print("✅ Core functionality validated")
        else:
            print("❌ Core functionality needs attention")
            
        if any("Performance" in name and success for name, (success, _, _) in self.results.items()):
            print("✅ Performance characteristics validated")
        elif any("Performance" in name for name in self.results.keys()):
            print("⚠️  Performance tests failed - check scalability")
        else:
            print("📝 Consider running performance tests with --include-performance")
            
        if any("HTTP" in name and success for name, (success, _, _) in self.results.items()):
            print("✅ HTTP transport validated")
        elif any("HTTP" in name for name in self.results.keys()):
            print("⚠️  HTTP transport tests failed")
        else:
            print("📝 Consider running HTTP tests with --include-http")


async def main():
    """Main test runner entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run MCP Agent test suites")
    parser.add_argument("--skip-performance", action="store_true", 
                       help="Skip performance tests (for faster runs)")
    parser.add_argument("--skip-http", action="store_true",
                       help="Skip HTTP transport tests")
    parser.add_argument("--test-file", type=str, 
                       help="Run only a specific test file")
    
    args = parser.parse_args()
    
    runner = TestRunner()
    
    if args.test_file:
        # Run specific test file
        if args.test_file not in runner.test_files.values():
            print(f"❌ Test file not found: {args.test_file}")
            print(f"Available test files: {', '.join(runner.test_files.values())}")
            return
        
        test_name = next(name for name, file in runner.test_files.items() if file == args.test_file)
        success, duration, output = await runner.run_test_file(test_name, args.test_file)
        
        if success:
            print(f"\n🎉 {test_name} completed successfully!")
        else:
            print(f"\n❌ {test_name} failed.")
            sys.exit(1)
    else:
        # Run all tests
        await runner.run_all_tests(
            skip_performance=args.skip_performance,
            skip_http=args.skip_http
        )
        
        # Exit with error code if any tests failed
        if any(not success for success, _, _ in runner.results.values()):
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
