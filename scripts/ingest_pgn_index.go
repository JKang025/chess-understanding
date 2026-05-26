package main

import (
	"bufio"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

// Example usage:
// go run scripts/ingest_pgn_index.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --db data/lichess_open_database/lichess_index.db
// go run scripts/ingest_pgn_index.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --db /tmp/lichess_index.db --test-run
// go run scripts/ingest_pgn_index.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --db /tmp/lichess_index.db --progress-interval 30s

type GameRecord struct {
	Raw       string
	Headers   map[string]string
	Index     int
	ByteStart int64
	ByteEnd   int64
}

type cliConfig struct {
	Input            string
	DBPath           string
	SourceFile       string
	TestRun          bool
	ProgressInterval time.Duration
}

var lichessSiteTokenPattern = regexp.MustCompile(`^[A-Za-z0-9]{8}$`)

func main() {
	start := time.Now()

	cfg, err := parseFlags()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	if err := run(cfg, start); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func parseFlags() (cliConfig, error) {
	var cfg cliConfig
	var progressIntervalRaw string

	flag.StringVar(&cfg.Input, "input", "", "Input .pgn file")
	flag.StringVar(&cfg.DBPath, "db", "", "SQLite DB output path")
	flag.StringVar(&cfg.SourceFile, "source-file", "", "Optional source file label stored per row")
	flag.BoolVar(&cfg.TestRun, "test-run", false, "Print per-game parsed values without writing to DB")
	flag.StringVar(&progressIntervalRaw, "progress-interval", "60s", "Progress log interval (e.g. 60s, 1m)")
	flag.Parse()

	if cfg.Input == "" {
		return cfg, errors.New("--input is required")
	}
	if !strings.HasSuffix(strings.ToLower(cfg.Input), ".pgn") {
		return cfg, errors.New("--input must be a .pgn file for v1")
	}
	if cfg.DBPath == "" && !cfg.TestRun {
		return cfg, errors.New("--db is required unless --test-run is set")
	}

	interval, err := time.ParseDuration(progressIntervalRaw)
	if err != nil {
		return cfg, fmt.Errorf("invalid --progress-interval: %w", err)
	}
	if interval < 0 {
		return cfg, errors.New("--progress-interval must be >= 0")
	}
	cfg.ProgressInterval = interval

	if cfg.SourceFile == "" {
		cfg.SourceFile = cfg.Input
	}

	return cfg, nil
}

func run(cfg cliConfig, start time.Time) error {
	inFile, err := os.Open(cfg.Input)
	if err != nil {
		return fmt.Errorf("failed to open input file: %w", err)
	}
	defer inFile.Close()

	var db *sql.DB
	var insertStmt *sql.Stmt

	if !cfg.TestRun {
		db, err = sql.Open("sqlite", cfg.DBPath)
		if err != nil {
			return fmt.Errorf("failed to open sqlite DB: %w", err)
		}
		defer db.Close()

		if err := createSchema(db); err != nil {
			return err
		}

		insertStmt, err = db.Prepare(`
			INSERT INTO games (
				game_id,
				source_file,
				byte_offset_start,
				byte_offset_end,
				event,
				site,
				date,
				round,
				white,
				black,
				result,
				utc_date,
				utc_time,
				white_elo,
				black_elo,
				white_rating_diff,
				black_rating_diff,
				eco,
				opening,
				time_control,
				termination,
				variant,
				movetext
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`)
		if err != nil {
			return fmt.Errorf("failed to prepare insert statement: %w", err)
		}
		defer insertStmt.Close()
	}

	seen := 0
	written := 0
	skipped := 0
	lastProgress := start

	for game := range parseGames(inFile) {
		seen++
		headers := game.Headers
		gameIDValue := sql.NullString{}
		if id, ok := extractGameID(headers["Site"]); ok {
			gameIDValue = sql.NullString{String: id, Valid: true}
		}

		if cfg.TestRun {
			printTestRun(game, gameIDValue)
			written++
		} else {
			_, err := insertStmt.Exec(
				gameIDValue,
				cfg.SourceFile,
				game.ByteStart,
				game.ByteEnd,
				headers["Event"],
				headers["Site"],
				headers["Date"],
				headers["Round"],
				headers["White"],
				headers["Black"],
				headers["Result"],
				headers["UTCDate"],
				headers["UTCTime"],
				headers["WhiteElo"],
				headers["BlackElo"],
				headers["WhiteRatingDiff"],
				headers["BlackRatingDiff"],
				headers["ECO"],
				headers["Opening"],
				headers["TimeControl"],
				headers["Termination"],
				headers["Variant"],
				extractMoveText(game.Raw),
			)
			if err != nil {
				skipped++
				fmt.Fprintf(os.Stderr, "warn: insert failed for game=%d: %v\n", game.Index, err)
			} else {
				written++
			}
		}

		if cfg.ProgressInterval > 0 && time.Since(lastProgress) >= cfg.ProgressInterval {
			fmt.Printf(
				"progress: seen=%d written=%d skipped=%d elapsed=%s\n",
				seen,
				written,
				skipped,
				time.Since(start).Round(time.Second),
			)
			lastProgress = time.Now()
		}
	}

	fmt.Printf("done: seen=%d written=%d skipped=%d\n", seen, written, skipped)
	if !cfg.TestRun {
		absDBPath, err := filepath.Abs(cfg.DBPath)
		if err == nil {
			fmt.Printf("db: %s\n", absDBPath)
		} else {
			fmt.Printf("db: %s\n", cfg.DBPath)
		}
	}
	fmt.Printf("elapsed: %s\n", time.Since(start).Round(time.Millisecond))

	return nil
}

func createSchema(db *sql.DB) error {
	schema := `
	CREATE TABLE IF NOT EXISTS games (
		row_id INTEGER PRIMARY KEY AUTOINCREMENT,
		game_id TEXT NULL,
		source_file TEXT NOT NULL,
		byte_offset_start INTEGER NOT NULL,
		byte_offset_end INTEGER NOT NULL,
		event TEXT,
		site TEXT,
		date TEXT,
		round TEXT,
		white TEXT,
		black TEXT,
		result TEXT,
		utc_date TEXT,
		utc_time TEXT,
		white_elo TEXT,
		black_elo TEXT,
		white_rating_diff TEXT,
		black_rating_diff TEXT,
		eco TEXT,
		opening TEXT,
		time_control TEXT,
		termination TEXT,
		variant TEXT,
		movetext TEXT
	);
	CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id);
	CREATE INDEX IF NOT EXISTS idx_games_source_offset ON games(source_file, byte_offset_start);
	CREATE INDEX IF NOT EXISTS idx_games_time_control ON games(time_control);
	CREATE INDEX IF NOT EXISTS idx_games_variant ON games(variant);
	CREATE INDEX IF NOT EXISTS idx_games_event ON games(event);
	CREATE INDEX IF NOT EXISTS idx_games_white_elo ON games(white_elo);
	CREATE INDEX IF NOT EXISTS idx_games_black_elo ON games(black_elo);
	`

	if _, err := db.Exec(schema); err != nil {
		return fmt.Errorf("failed to create schema/indexes: %w", err)
	}
	return nil
}

func parseGames(reader io.Reader) <-chan GameRecord {
	out := make(chan GameRecord)

	go func() {
		defer close(out)

		buffered := bufio.NewReaderSize(reader, 256*1024)

		var rawBuilder strings.Builder
		headers := map[string]string{}
		inGame := false
		moveStarted := false
		gameIndex := 0

		var currentOffset int64
		var gameStartOffset int64

		emitGame := func(endOffset int64) {
			if !inGame {
				return
			}

			gameIndex++
			raw := rawBuilder.String()
			copiedHeaders := make(map[string]string, len(headers))
			for k, v := range headers {
				copiedHeaders[k] = v
			}

			out <- GameRecord{
				Raw:       raw,
				Headers:   copiedHeaders,
				Index:     gameIndex,
				ByteStart: gameStartOffset,
				ByteEnd:   endOffset,
			}

			rawBuilder.Reset()
			headers = map[string]string{}
			inGame = false
			moveStarted = false
		}

		for {
			lineStart := currentOffset
			lineWithNewline, readErr := buffered.ReadString('\n')

			if len(lineWithNewline) > 0 {
				currentOffset += int64(len(lineWithNewline))
				trimmed := strings.TrimSpace(lineWithNewline)

				if strings.HasPrefix(trimmed, "[") {
					if inGame && moveStarted {
						emitGame(lineStart)
					}
					if !inGame {
						gameStartOffset = lineStart
					}
					inGame = true
					rawBuilder.WriteString(lineWithNewline)
					if key, value, ok := parseHeaderLine(trimmed); ok {
						headers[key] = value
					}
				} else if inGame {
					rawBuilder.WriteString(lineWithNewline)
					if trimmed != "" {
						moveStarted = true
					}
				}
			}

			if readErr != nil {
				if readErr == io.EOF {
					if inGame {
						emitGame(currentOffset)
					}
					break
				}
				fmt.Fprintf(os.Stderr, "warn: parse read error: %v\n", readErr)
				if inGame {
					emitGame(currentOffset)
				}
				break
			}
		}
	}()

	return out
}

func extractMoveText(raw string) string {
	lines := strings.Split(raw, "\n")
	moveLines := make([]string, 0, len(lines))
	inHeaders := true
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if inHeaders {
			if strings.HasPrefix(trimmed, "[") {
				continue
			}
			if trimmed == "" {
				continue
			}
			inHeaders = false
		}
		if !inHeaders {
			if trimmed == "" {
				continue
			}
			moveLines = append(moveLines, strings.TrimSpace(line))
		}
	}
	return strings.Join(moveLines, "\n")
}

func parseHeaderLine(line string) (string, string, bool) {
	if !strings.HasPrefix(line, "[") || !strings.HasSuffix(line, "]") {
		return "", "", false
	}
	inner := strings.TrimSuffix(strings.TrimPrefix(line, "["), "]")
	firstQuote := strings.Index(inner, "\"")
	lastQuote := strings.LastIndex(inner, "\"")
	if firstQuote <= 0 || lastQuote <= firstQuote {
		return "", "", false
	}
	key := strings.TrimSpace(inner[:firstQuote])
	value := inner[firstQuote+1 : lastQuote]
	if key == "" {
		return "", "", false
	}
	return key, value, true
}

func extractGameID(site string) (string, bool) {
	site = strings.TrimSpace(site)
	if site == "" {
		return "", false
	}

	site = strings.TrimPrefix(site, "https://")
	site = strings.TrimPrefix(site, "http://")
	site = strings.TrimPrefix(site, "www.")

	if !strings.HasPrefix(strings.ToLower(site), "lichess.org/") {
		return "", false
	}

	pathPart := site[len("lichess.org/"):]
	if pathPart == "" {
		return "", false
	}

	end := len(pathPart)
	for i, r := range pathPart {
		if r == '/' || r == '?' || r == '#' {
			end = i
			break
		}
	}
	token := pathPart[:end]
	if lichessSiteTokenPattern.MatchString(token) {
		return token, true
	}

	return "", false
}

func printTestRun(game GameRecord, gameID sql.NullString) {
	idText := "NULL"
	if gameID.Valid {
		idText = gameID.String
	}
	headers := game.Headers

	fmt.Printf(
		"game=%d gameID=%s byteStart=%d byteEnd=%d event=%q site=%q whiteElo=%q blackElo=%q timeControl=%q variant=%q\n",
		game.Index,
		idText,
		game.ByteStart,
		game.ByteEnd,
		headers["Event"],
		headers["Site"],
		headers["WhiteElo"],
		headers["BlackElo"],
		headers["TimeControl"],
		headers["Variant"],
	)
}
