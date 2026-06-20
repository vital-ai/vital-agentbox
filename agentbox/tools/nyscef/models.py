"""
Pydantic Input/Output models for NYSCEF court case agent tools.

"""

from typing import Literal

from pydantic import BaseModel, Field


# --- Shared ---

class NyscefCaseSummary(BaseModel):
    """Summary of a NYSCEF case returned by search."""
    index_number: str | None = Field(default=None, description="Case index number (e.g. '100234/2024')")
    docket_id: str | None = Field(default=None, description="NYSCEF internal docket ID")
    caption: str | None = Field(default=None, description="Short case caption (e.g. 'Smith v. Jones')")
    case_type: str | None = Field(default=None, description="Case type (e.g. 'Commercial', 'Torts')")
    case_status: str | None = Field(default=None, description="Case status (e.g. 'Active', 'Disposed')")
    court: str | None = Field(default=None, description="Court name")
    efiling_status: str | None = Field(default=None, description="E-filing status")
    filing_date: str | None = Field(default=None, description="Filing date")


class NyscefParty(BaseModel):
    """A party in a NYSCEF case."""
    name: str | None = Field(default=None, description="Party name")
    role: str | None = Field(default=None, description="Party role (e.g. 'Plaintiff', 'Defendant')")
    attorney: str | None = Field(default=None, description="Attorney or firm name")


class NyscefDocketEntry(BaseModel):
    """A docket entry (filing) in a NYSCEF case."""
    filing_date: str | None = Field(default=None, description="Date filed")
    doc_index: str | None = Field(default=None, description="Document index number")
    document_type: str | None = Field(default=None, description="Document type")
    filed_by: str | None = Field(default=None, description="Filed by (party name)")
    description: str | None = Field(default=None, description="Description of the filing")


class NyscefCaseDetail(BaseModel):
    """Full detail of a NYSCEF case from its docket page."""
    docket_id: str | None = Field(default=None, description="NYSCEF internal docket ID")
    index_number: str | None = Field(default=None, description="Case index number")
    case_type: str | None = Field(default=None, description="Case type")
    case_status: str | None = Field(default=None, description="Case status")
    court: str | None = Field(default=None, description="Court name")
    judge: str | None = Field(default=None, description="Assigned judge")
    filing_date: str | None = Field(default=None, description="Filing date")
    caption: str | None = Field(default=None, description="Full case caption")
    parties: list[NyscefParty] = Field(default_factory=list, description="Parties in the case")
    docket_entries: list[NyscefDocketEntry] = Field(default_factory=list, description="Docket entries (filings)")


# --- Case Search ---

class NyscefCaseSearchInput(BaseModel):
    """Input model for NYSCEF case search tool"""
    business_name: str | None = Field(default=None, description="Business or organization name to search")
    last_name: str | None = Field(default=None, description="Party last name")
    first_name: str | None = Field(default=None, description="Party first name")
    index_number: str | None = Field(default=None, description="Case index number (e.g. '100234/2024')")
    start_date: str | None = Field(default=None, description="Filing date range start (MM/DD/YYYY)")
    end_date: str | None = Field(default=None, description="Filing date range end (MM/DD/YYYY)")

    model_config = {
        "json_schema_extra": {
            "example": {"business_name": "Acme Corp"}
        }
    }


class NyscefCaseSearchOutput(BaseModel):
    """Output model for NYSCEF case search tool"""
    tool: Literal["nyscef_case_search_tool"] = Field(..., description="Tool identifier")
    cases: list[NyscefCaseSummary] = Field(default_factory=list, description="Matching cases")
    total_count: int | None = Field(default=None, description="Total number of matching cases")
    error: str | None = Field(default=None, description="Error message if search failed")

    model_config = {
        "json_schema_extra": {
            "example": {
                "tool": "nyscef_case_search_tool",
                "cases": [
                    {
                        "index_number": "100234/2024",
                        "caption": "Smith v. Jones",
                        "case_type": "Commercial",
                        "court": "New York County Supreme Court",
                    }
                ],
                "total_count": 1,
            }
        }
    }


# --- Case Detail ---

class NyscefCaseDetailInput(BaseModel):
    """Input model for NYSCEF case detail tool"""
    docket_id: str = Field(..., description="NYSCEF docket ID", min_length=1)
    include_filings: bool = Field(default=True, description="Whether to include docket entries/filings")

    model_config = {
        "json_schema_extra": {
            "example": {"docket_id": "nJKJhDpiLZHSfHrvVE_PLUS_Jg==", "include_filings": True}
        }
    }


class NyscefCaseDetailOutput(BaseModel):
    """Output model for NYSCEF case detail tool"""
    tool: Literal["nyscef_case_detail_tool"] = Field(..., description="Tool identifier")
    case: NyscefCaseDetail | None = Field(default=None, description="Case details")
    error: str | None = Field(default=None, description="Error message if lookup failed")

    model_config = {
        "json_schema_extra": {
            "example": {
                "tool": "nyscef_case_detail_tool",
                "case": {
                    "docket_id": "nJKJhDpiLZHSfHrvVE_PLUS_Jg==",
                    "index_number": "100234/2024",
                    "caption": "Smith v. Jones",
                    "court": "New York County Supreme Court",
                    "parties": [
                        {"name": "John Smith", "role": "Plaintiff", "attorney": "Law Firm LLP"}
                    ],
                },
            }
        }
    }
