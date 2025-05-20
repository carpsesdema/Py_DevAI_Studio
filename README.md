# PyDevAI_Studio: Your AI-Powered Python Development Environment

PyDevAI_Studio is a desktop application designed to supercharge your Python development workflow by integrating powerful Large Language Models (LLMs) and a local Retrieval Augmented Generation (RAG) system directly into your coding environment.

## Core Workflow

1.  **Brainstorm & Design:** You, the Python programmer, conceptualize and design your Python programs or modifications.
2.  **Collaborate with ChatLLM:** Discuss your ideas with the primary ChatLLM integrated into the PyDevAI_Studio GUI. This LLM helps you refine requirements, explore options, and acts as an intelligent assistant.
3.  **Instruction Generation:** The ChatLLM translates your high-level plans and discussions into detailed, structured instructions specifically tailored for a secondary, specialized CodingLLM.
4.  **Code Generation with RAG:** The CodingLLM, equipped with access to your project-specific local RAG (knowledge base of your existing code, documentation, etc.), generates professional-grade Python code based on the instructions.
5.  **IDE Integration:**
    * **File Management:** PyDevAI_Studio creates new files or modifies existing ones directly within your active project directory.
    * **Code Viewer:** Review, edit (future), and manage all AI-generated code within an integrated code viewer.
    * **Real-time Logging:** Monitor all LLM communications (prompts and responses) in a dedicated, modern terminal window.

## Key Features (Planned)

* **Dual LLM Architecture:**
    * **Primary ChatLLM:** For user interaction, planning, and instruction generation.
    * **Specialized CodingLLM:** Optimized for high-quality Python code generation, adhering to best practices (PEP8, type hinting, docstrings).
* **Local RAG Integration:** Provide deep contextual awareness to the CodingLLM by indexing your project files and relevant documentation.
* **Integrated Code Viewer/Editor:** Seamlessly view and manage generated code.
* **Direct File System Operations:** Create and modify project files as instructed.
* **Live LLM Communication Log:** A transparent view of all LLM interactions.
* **Python-focused:** Designed to streamline the workflow of Python freelance programmers.
* **Extensible Backend:** Leverages a flexible backend system for LLM communication (inspired by AvA's adapters).

## Technology Stack (Proposed)

* **GUI:** Python with PyQt6
* **LLM Interaction:**
    * Adapters for various local (Ollama) and cloud-based (Gemini, OpenAI) LLMs.
* **RAG System:**
    * FAISS for vector storage/search.
    * Sentence Transformers for embeddings.
    * Langchain (or similar) for RAG orchestration.
* **Core:** Python

## Project Goals

* To provide a clean, efficient, and AI-augmented development environment.
* To ensure the CodingLLM produces professional-grade, maintainable Python code.
* To streamline the process from idea to implementation for Python projects.