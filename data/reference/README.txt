AskSage Proof Agent - Reference documents (RAG attachments)
============================================================

Drop the three gate documents into THIS folder. The review nodes attach
their text to the prompts of whichever nodes you check in the UI.

Expected file names (the registry in configs/references.json looks these up):

  ari_publication_manual   ->  ARI Internal Publication Manual
  army_ar_rag              ->  Army AR / Army Publication Record (RAG)
  dtic_regs                ->  DTIC Publication Regulations

Accepted formats (use one, keep the base name):
  ari_publication_manual.txt   (or .md, .pdf, .docx)
  army_ar_rag.txt              (or .md, .pdf, .docx)
  dtic_regs.txt                (or .md, .pdf, .docx)

Examples:
  data/reference/ari_publication_manual.pdf
  data/reference/army_ar_rag.docx
  data/reference/dtic_regs.txt

How to use in the dashboard:
  1. Put the files in this folder (Docker: the ./data folder is bind-mounted,
     so no rebuild is needed).
  2. Refresh the browser page. Each node's editor shows the documents as
     [Loaded] once they are found.
  3. Check the documents each node should attach, then press Save on that
     node. The review injects the attached text into that node's prompts.

Notes:
  - PDF text extraction needs a text-based PDF (scanned images are not read).
  - A document that exists but cannot be read renders as
    [[REFERENCE NOT LOADED: title]] in the prompt instead of being silently
    skipped, so a run never mistakes an absent manual for an empty one.
