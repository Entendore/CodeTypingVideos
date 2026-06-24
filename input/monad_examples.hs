{- ====================================================================
   EXPECTED OUTPUT WHEN RUNNING THIS FILE (runhaskell monad_examples.hs)
   ====================================================================
=== Monad Examples in Haskell ===

1. MAYBE MONAD (Handling Failure)
-----------------------------
Valid birth year: Just 34.0
Invalid birth year: Nothing

2. LIST MONAD (Non-determinism / Combinations)
----------------------------------------------
Red Shirt with Jeans
Red Shirt with Khakis
Red Shirt with Shorts
Blue Shirt with Jeans
Blue Shirt with Khakis
Blue Shirt with Shorts

3. IO MONAD (Side Effects)
-------------------------
What is your name?
Alice
What is your favorite color?
Blue
Hello Alice! Blue is a great choice.
-}

main :: IO ()
main = do
    putStrLn "=== Monad Examples in Haskell ===\n"
    
    -- 1. The Maybe Monad
    putStrLn "1. MAYBE MONAD (Handling Failure)"
    putStrLn "-----------------------------"
    let successResult = calculateAge 2024 1990
    let failureResult = calculateAge 2024 2030
    
    putStrLn $ "Valid birth year: " ++ show successResult
    putStrLn $ "Invalid birth year: " ++ show failureResult ++ "\n"
    
    -- 2. The List Monad
    putStrLn "2. LIST MONAD (Non-determinism / Combinations)"
    putStrLn "----------------------------------------------"
    let outfits = generateOutfits
    mapM_ putStrLn outfits
    putStrLn ""
    
    -- 3. The IO Monad
    putStrLn "3. IO MONAD (Side Effects)"
    putStrLn "-------------------------"
    askForName



-- ==========================================
-- 1. THE MAYBE MONAD
-- ==========================================
-- The Maybe monad is used for computations that might fail.
-- It either returns `Just a` (success) or `Nothing` (failure).

safeDivide :: Double -> Double -> Maybe Double
safeDivide _ 0 = Nothing   -- Dividing by zero fails!
safeDivide x y = Just (x / y)

-- We want to do: (100 / 2) / 5 / 0
-- Without monads, we would have to write nested case statements.
-- WITH monads, the `<-` operator handles the failure automatically.
-- If any step returns `Nothing`, the whole function short-circuits and returns `Nothing`.
calculateAge :: Int -> Int -> Maybe Double
calculateAge currentYear birthYear = do
    let yearsDiff = fromIntegral (currentYear - birthYear)
    
    -- If yearsDiff is negative, we fail immediately
    age <- if yearsDiff < 0 then Nothing else Just yearsDiff
    
    -- Let's do a useless but safe division just to show chaining
    result <- safeDivide age 1.0 
    
    return result


-- ==========================================
-- 2. THE LIST MONAD
-- ==========================================
-- The List monad treats a list as a set of possible outcomes.
-- The `<-` operator extracts *each* item from the list one by one, 
-- creating a Cartesian product (every possible combination).

shirts :: [String]
shirts = ["Red Shirt", "Blue Shirt"]

pants :: [String]
pants = ["Jeans", "Khakis", "Shorts"]

-- This will generate every possible combination of shirt and pants.
generateOutfits :: [String]
generateOutfits = do
    s <- shirts   -- Bind a shirt
    p <- pants    -- Bind a pair of pants
    return (s ++ " with " ++ p) -- Combine them


-- ==========================================
-- 3. THE IO MONAD
-- ==========================================
-- Haskell is a pure language. Functions cannot have side effects 
-- (like reading from the keyboard or printing to the screen) 
-- UNLESS they are wrapped in the IO monad.
-- The IO monad sequences real-world actions strictly in the order they appear.

askForName :: IO ()
askForName = do
    putStrLn "What is your name?"
    name <- getLine              -- <--- Pauses program, waits for user input
    
    putStrLn "What is your favorite color?"
    color <- getLine             -- <--- Pauses program again
    
    -- We can use pure functions (like ++) inside the IO monad
    let greeting = "Hello " ++ name ++ "! " ++ color ++ " is a great choice."
    
    putStrLn greeting