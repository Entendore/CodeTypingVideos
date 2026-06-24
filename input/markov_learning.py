import random
import re
from collections import defaultdict, Counter

class MarkovModel:
    """
    A robust Markov Chain implementation supporting N-grams.
    
    Theory:
    - The 'Order' (n) determines how many previous words (context) the model sees.
    - Order 1: P(Current | Previous)
    - Order 2: P(Current | Previous1, Previous2)
    """
    
    def __init__(self, order=2):
        # ORDER: The "memory" of the chain. Higher order = more coherent, less creative.
        self.order = order
        
        # MODEL STRUCTURE:
        # We use a defaultdict of Counters.
        # Key: A tuple representing the current state (n-gram), e.g., ('the', 'quick')
        # Value: A Counter mapping possible next words to their frequency, e.g., {'brown': 1, 'red': 5}
        self.chain = defaultdict(Counter)
        
        # Used for fallback if we get stuck during generation (cold start problem)
        self.start_states = []

    def _tokenize(self, text):
        """
        Preprocessing: Convert raw text into a clean list of tokens.
        
        Expert Note: Production systems use NLTK or spaCy for tokenization to handle 
        edge cases like contractions ("don't") and punctuation.
        Here, we use a regex strategy that keeps sentence-ending punctuation attached 
        to words, which helps the model learn where sentences stop.
        """
        # Replace newlines with spaces, then find words or standalone punctuation
        # This regex keeps words like "end." intact
        tokens = re.findall(r"\w+(?:['-]\w+)*|[.,!?;]", text.lower())
        return tokens

    def train(self, text):
        """
        Learning Phase: Construct the transition matrix.
        """
        tokens = self._tokenize(text)
        num_tokens = len(tokens)
        
        if num_tokens <= self.order:
            raise ValueError("Text is too short for the specified order.")

        # Iterate through the text to build N-grams
        for i in range(num_tokens - self.order):
            # 1. Define the State (Context)
            # A tuple is hashable and can be used as a dictionary key.
            state = tuple(tokens[i : i + self.order])
            
            # 2. Define the Observation (The word following the state)
            next_word = tokens[i + self.order]
            
            # 3. Update the frequency map
            self.chain[state][next_word] += 1
            
            # Track states that occur at the beginning of sentences (heuristic for generation)
            # Note: In a rigorous system, we would specifically detect sentence boundaries.
            if i == 0 or tokens[i-1] in ".!?":
                self.start_states.append(state)

        print(f"[Training] Model built with {len(self.chain)} unique states.")

    def _weighted_random_choice(self, counter):
        """
        Sampling: Selects an item from a Counter based on probability weights.
        
        Math: P(w) = Count(w) / Total_Count
        """
        population = list(counter.keys())
        weights = list(counter.values())
        
        # random.choices returns a list, so we take index [0]
        return random.choices(population, weights=weights, k=1)[0]

    def generate(self, seed_text=None, max_length=50):
        """
        Generation Phase: Walk the chain.
        """
        if not self.chain:
            return "Error: Model not trained."

        # --- DETERMINE START STATE ---
        if seed_text:
            # If user provides a seed, we tokenize it and take the last 'order' words.
            seed_tokens = self._tokenize(seed_text)
            if len(seed_tokens) < self.order:
                current_state = tuple(seed_tokens + [""] * (self.order - len(seed_tokens)))
            else:
                current_state = tuple(seed_tokens[-self.order:])
        else:
            # Cold Start: Pick a random state known to start a sequence.
            current_state = random.choice(self.start_states)

        # Build the output list starting with the current state
        output = list(current_state)

        # --- WALK THE CHAIN ---
        for _ in range(max_length):
            # Look up the current state in our transition matrix
            possibilities = self.chain.get(current_state)

            if not possibilities:
                # DEAD END: We reached a state we've never seen before.
                # Strategy: Break the sentence immediately to avoid gibberish.
                break

            # Sample the next word based on learned probabilities
            next_word = self._weighted_random_choice(possibilities)
            output.append(next_word)

            # Update state: Slide the window forward.
            # New state drops the oldest word and adds the new word.
            current_state = tuple(output[-self.order:])
            
            # Optional: Stop if we hit terminal punctuation
            if next_word in ".!?":
                # A small chance to continue (for multi-sentence generation) 
                # or break here. Let's break for cleaner single sentences.
                if random.random() > 0.3: 
                    break

        return " ".join(output).capitalize()

# ==========================================
# EXPERT DEMONSTRATION
# ==========================================

if __name__ == "__main__":
    # 1. The Corpus: Larger, more complex text reveals the power of N-grams.
    corpus = """
    The science of operations, as derived from mathematics, is the true basis of teaching. 
    In learning anything, we must start with the simple and move to the complex.
    Logic is the foundation of all reasoning. Without logic, we are lost.
    Data is not information, information is not knowledge, knowledge is not wisdom.
    """

    # 2. Initialize with Order 2 (Bigram model).
    # This means the model predicts words based on the *previous 2 words*.
    # Change order to 1 to see how coherence degrades.
    model = MarkovModel(order=2)

    # 3. Train
    try:
        model.train(corpus)
    except ValueError as e:
        print(e)
        exit()

    # 4. Generate: Seedless
    print("\n--- Random Generations (Order 2) ---")
    for i in range(3):
        print(f"> {model.generate(max_length=20)}")

    # 5. Generate: Seeded
    # Notice how the context of "science of" constrains the next word choices significantly
    # compared to just starting with "science".
    seed = "science of"
    print(f"\n--- Seeded Generation ('{seed}') ---")
    print(f"> {model.generate(seed_text=seed)}")