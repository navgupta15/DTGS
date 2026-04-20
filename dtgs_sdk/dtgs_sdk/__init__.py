"""
DTGS SDK — Client SDK for the Dynamic Tool Generation System.

Provides easy integration with DTGS catalog servers for LLM agent tool
discovery, filtering, and execution.

Usage:
    from dtgs_sdk import DTGSToolkit

    toolkit = DTGSToolkit("http://dtgs-server:8000", namespace="my-service")
    tools = toolkit.get_tools(query="refund payment")
    result = toolkit.execute("refundPayment", {"orderId": "5042"})
"""

from dtgs_sdk.toolkit import DTGSToolkit
from dtgs_sdk.client import DTGSClient

__all__ = ["DTGSToolkit", "DTGSClient"]
__version__ = "0.1.0"
