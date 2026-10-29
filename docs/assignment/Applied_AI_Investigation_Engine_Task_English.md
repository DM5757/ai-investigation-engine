# Applied AI – AI Investigation Engine Task

**Talent Growth Program**  
**English translation of the original Georgian assignment**

## Project Description

Your goal is to create an artificial intelligence-based system capable of searching for, analyzing, connecting, and generating well-supported answers from information contained in large volumes of documents.

The project must not be merely a document-chat application (Chat with PDF).

The system must be able to process questions whose answers require examining several sources simultaneously, comparing different pieces of information, and drawing logical conclusions.

**Example:**

An organization has technical documentation, incident reports, a history of system changes, and other materials.

A user asks:

> “Which system changes caused disruptions in payment processing in March, which services were affected, and which documents support this?”

The system must retrieve relevant information, connect facts found across different documents, and provide an answer with references to the sources.

If the information is insufficient or contradictory, the system must identify this and must not invent facts.

## 2. Main Requirements

### Document Processing

The system must be capable of accepting, processing, and indexing documents in different formats.

**Mandatory requirements:**

- Support at least three different file formats.
- Extract text and important metadata from documents.
- Split text into chunks (Chunking).
- Handle duplicate information.
- Add new documents, update existing documents, and delete documents.
- Compare at least two chunking strategies.

You must select the processing architecture yourself and justify the decisions made.

### Vector Database and Search

The project must use a vector database or a database that supports vector search.

Possible technologies include:

- Qdrant
- Pinecone
- Neon PostgreSQL + pgvector
- Supabase + pgvector
- Weaviate
- Chroma
- Any other suitable alternative.

Ordinary SQL text search alone does not satisfy this requirement.

The system must use Embeddings and Semantic Search.

In addition, Hybrid Search must be implemented, combining semantic search and keyword-based search.

You must implement at least one custom algorithmic component for search or result ranking. It is not permitted to base the entire search logic solely on ready-made libraries.

### LLM Integration and RAG

The system must use at least one Large Language Model.

**Mandatory requirements:**

- Use a Retrieval-Augmented Generation (RAG) architecture.
- Combine information obtained from different documents.
- Process complex questions in multiple steps.
- Generate answers based on relevant evidence.
- Implement a source-reference and citation mechanism.
- Attempt to detect contradictory information.
- Abstain from answering when information is insufficient.
- Handle errors and limitations in communication with the LLM.

The system must include at least one Tool Calling mechanism or an equivalent structured tool-invocation mechanism.

You are free to choose the model, Prompt Engineering approach, and frameworks used.

### Evaluation of Results

The candidate must create their own automated evaluation system.

**Minimum requirements:**

- At least 40 test questions.
- Simple and multi-step questions.
- Questions that require connecting information across several documents.
- Questions for which no answer exists in the data.
- Questions based on contradictory information.
- Quantitative evaluation of retrieval quality and answer quality.
- Comparison of at least two different configurations.

Appropriate metrics must be used for evaluation, for example Recall@K, MRR, Answer Correctness, and Citation Accuracy.

You must present not only the results but also their analysis: where the system makes mistakes, why those mistakes occur, and how it could be improved.

### Backend and User Interface

The project must have a Python-based backend and a functional user interface.

Users must be able to add and manage documents, ask questions, and view the sources supporting generated answers.

You must determine the API structure, technological architecture, and user-interface implementation approach yourself.

Priority is given to correct functionality, code quality, and system reliability rather than the complexity of the visual design.

## 3. Dataset

You must use the dataset attached to this assignment to complete the project.

The use of additional public data or synthetic documents is also permitted.

**Mandatory requirements:**

- Process at least 50,000 documents or independent text records.
- Retrieve related information across multiple documents.
- Preserve and identify sources.
- Handle incomplete and contradictory information.
- Enable reproducible evaluation.

It is not necessary to use the entire dataset if it is very large. You may select a reproducible subset and justify your selection.

You may choose one or more of the following datasets:

- [HotpotQA](https://huggingface.co/datasets/hotpotqa/hotpot_qa)
- [RAGBench](https://huggingface.co/datasets/galileo-ai/ragbench)
- [2WikiMultihopQA](https://huggingface.co/datasets/xanhho/2WikiMultihopQA)
- [Post-mortems collection](https://github.com/danluu/post-mortems)

## 4. Free Hosting and Deployment

The project must be deployed on the internet and be accessible through a public link.

You must use a free hosting service or the free tier of a hosting service.

Possible platforms include:

- Render
- Vercel
- Hugging Face Spaces
- Koyeb
- Oracle Cloud Always Free
- Any other free alternative.

The vector database may also be hosted on a free cloud tier offered by an appropriate platform.

**Mandatory requirements:**

- The system must actually be running and accessible via a public URL.
- Hosting and database integration must function correctly.
- Data must persist after the application restarts.
- API keys and other secrets must be protected.
- The deployment architecture must be described.
- Costs, resources, and free-tier limitations must be taken into account.

It must be possible to complete the project without purchasing paid infrastructure.

Free hosting limitations, such as the application going to sleep or request limits, are acceptable if they are properly documented and do not prevent demonstration of the core functionality.

## 5. Technical Quality

You are expected to provide:

- Clear and modular Python code.
- Proper separation of responsibilities.
- Error handling.
- Automated tests.
- Correct integration with the database and external APIs.
- Secure management of environment configuration.
- Technical documentation.
- An understanding of system performance and LLM costs.

The use of specific libraries or design patterns is not mandatory.

## 6. Additional Challenges (Bonus)

The following will receive additional consideration:

- Comparison of multiple LLMs or Embedding models.
- Multi-agent or Agentic RAG architecture.
- A more advanced re-ranking mechanism.
- Testing against Prompt Injection.
- Caching and performance optimization.
- Streaming responses.
- Detailed Monitoring and Observability.
- Performance testing on large volumes of data.

Additional functionality does not replace the core requirements.

## 7. What You Must Submit

Upon completion of the assignment, you must submit:

1. **GitHub Repository** — full source code and project history.
2. **Live Demo** — a link to the deployed application.
3. **README** — project description, architecture, setup instructions, and justification of technical choices.
4. **Evaluation Report** — testing methodology, metrics, results, and analysis.
5. **AI Usage Report** — which AI tools were used, how they helped, and what you changed independently.

## 8. Interview and Code Defense

The use of AI tools is permitted while completing the project.

However, you are fully responsible for the submitted code, regardless of whether you wrote it yourself or used AI tools to assist you.

During the technical interview, you will be required to:

- Explain your architecture.
- Discuss a specific section of your code in detail.
- Describe the operation of the RAG Pipeline step by step.
- Identify and fix bugs in the code.
- Add new functionality or modify existing functionality on the spot.
- Justify algorithms and technical decisions.

The use of AI assistants is prohibited during the practical part of the interview.

The evaluation will consider not only the final product, but also the candidate’s actual technical knowledge and ability to solve problems independently.
