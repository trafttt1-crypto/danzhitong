from .baidu_ocr import get_baidu_access_token, baidu_ocr, pdf_ocr
from .deepseek_audit import (
    build_lc_prefix, deepseek_audit,
    deepseek_lc_review, deepseek_lc_fields, parse_lc_fields,
)
from .history import init_db, get_db, close_db, save_audit_record
from .pdf_export import (
    generate_pdf, generate_docs_pdf, generate_fixed_pdf, generate_discrepancy_pdf,
    parse_report_section,
)
from .doc_generator import generate_docs, amount_to_english, as_text, to_dec
from .archive import (
    init_archive, save_archive, query_archive, get_archive_stats, build_excel,
    get_archive_db, extract_doc_fields,
)
from .lc_deadline import presentation_deadline, build_deadline_facts, parse_flexible_date
from .discrepancy import parse_issues, rule_basis
from .practice import (
    init_practice, grade, list_cases, get_case, create_case, delete_case, save_attempt,
)
