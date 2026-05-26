package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Example usage:
// go run scripts/filter_lichess_games.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --max-games 10000
// go run scripts/filter_lichess_games.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --min-elo 1800 --min-speed blitz --variant Standard
// go run scripts/filter_lichess_games.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --time-control-prefix 600+ --test-run --max-games 5
// go run scripts/filter_lichess_games.go --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --rated-only --max-games 5000

type Speed int

const (
	Bullet Speed = iota
	Blitz
	Rapid
	Classical
)

type GameRecord struct {
	Raw     string
	Headers map[string]string
	Index   int
}

type FilterConfig struct {
	MinElo            *int
	MaxElo            *int
	TimeControlPrefix string
	MinSpeed          *Speed
	Variant           string
	RatedOnly         bool
}

type cliConfig struct {
	Input             string
	OutDir            string
	OutputName        string
	MaxGames          int
	HasMaxGames       bool
	TestRun           bool
	TimeControlPrefix string
	Variant           string
	RatedOnly         bool
	MinElo            *int
	MaxElo            *int
	MinSpeed          *Speed
}

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
	var minEloFlag int
	var maxEloFlag int
	var minSpeedFlag string

	flag.StringVar(&cfg.Input, "input", "", "Input .pgn file")
	flag.StringVar(&cfg.OutDir, "out-dir", "data/filtered_lichess", "Directory to store filtered PGN output")
	flag.StringVar(&cfg.OutputName, "output-name", "", "Optional output filename. Default: <input_stem>.filtered.pgn")
	flag.IntVar(&cfg.MaxGames, "max-games", 0, "Stop after writing this many matched games")
	flag.IntVar(&minEloFlag, "min-elo", 0, "Minimum allowed min(player Elo)")
	flag.IntVar(&maxEloFlag, "max-elo", 0, "Maximum allowed max(player Elo)")
	flag.StringVar(&cfg.TimeControlPrefix, "time-control-prefix", "", "Keep games where TimeControl starts with this value")
	flag.StringVar(&minSpeedFlag, "min-speed", "", "Minimum speed bucket: bullet|blitz|rapid|classical")
	flag.StringVar(&cfg.Variant, "variant", "", "Exact Variant header match")
	flag.BoolVar(&cfg.RatedOnly, "rated-only", false, "Keep only rated games")
	flag.BoolVar(&cfg.TestRun, "test-run", false, "Print parsed values and match outcome for each game")

	flag.Parse()

	if cfg.Input == "" {
		return cfg, errors.New("--input is required")
	}
	if !strings.HasSuffix(strings.ToLower(cfg.Input), ".pgn") {
		return cfg, errors.New("--input must be a .pgn file for v1")
	}

	if cfg.MaxGames < 0 {
		return cfg, errors.New("--max-games must be >= 1 when provided")
	}
	if cfg.MaxGames > 0 {
		cfg.HasMaxGames = true
	}

	if minEloWasSet() {
		if minEloFlag < 0 {
			return cfg, errors.New("--min-elo must be >= 0")
		}
		cfg.MinElo = &minEloFlag
	}
	if maxEloWasSet() {
		if maxEloFlag < 0 {
			return cfg, errors.New("--max-elo must be >= 0")
		}
		cfg.MaxElo = &maxEloFlag
	}
	if cfg.MinElo != nil && cfg.MaxElo != nil && *cfg.MinElo > *cfg.MaxElo {
		return cfg, errors.New("--min-elo must be <= --max-elo")
	}

	if minSpeedFlag != "" {
		speed, ok := parseSpeed(minSpeedFlag)
		if !ok {
			return cfg, errors.New("--min-speed must be one of: bullet, blitz, rapid, classical")
		}
		cfg.MinSpeed = &speed
	}

	return cfg, nil
}

func run(cfg cliConfig, start time.Time) error {
	inFile, err := os.Open(cfg.Input)
	if err != nil {
		return fmt.Errorf("failed to open input file: %w", err)
	}
	defer inFile.Close()

	if err := os.MkdirAll(cfg.OutDir, 0o755); err != nil {
		return fmt.Errorf("failed to create output dir: %w", err)
	}

	outName := cfg.OutputName
	if outName == "" {
		outName = defaultOutputName(cfg.Input)
	}
	outPath := filepath.Join(cfg.OutDir, outName)

	outFile, err := os.Create(outPath)
	if err != nil {
		return fmt.Errorf("failed to create output file: %w", err)
	}
	defer outFile.Close()

	filterCfg := FilterConfig{
		MinElo:            cfg.MinElo,
		MaxElo:            cfg.MaxElo,
		TimeControlPrefix: cfg.TimeControlPrefix,
		MinSpeed:          cfg.MinSpeed,
		Variant:           cfg.Variant,
		RatedOnly:         cfg.RatedOnly,
	}

	gamesSeen := 0
	gamesWritten := 0
	lastProgressLog := start

	for game := range parseGames(inFile) {
		gamesSeen++
		match, reasons := matches(game, filterCfg)

		if cfg.TestRun {
			printTestRun(game, match, reasons)
		}

		if time.Since(lastProgressLog) >= time.Minute {
			elapsed := time.Since(start)
			fmt.Printf(
				"progress: seen=%d written=%d elapsed=%s\n",
				gamesSeen,
				gamesWritten,
				elapsed.Round(time.Second),
			)
			lastProgressLog = time.Now()
		}

		if !match {
			continue
		}

		if _, err := outFile.WriteString(game.Raw); err != nil {
			return fmt.Errorf("failed writing matched game: %w", err)
		}
		if !strings.HasSuffix(game.Raw, "\n\n") {
			if _, err := outFile.WriteString("\n\n"); err != nil {
				return fmt.Errorf("failed writing game separator: %w", err)
			}
		}

		gamesWritten++
		if cfg.HasMaxGames && gamesWritten >= cfg.MaxGames {
			break
		}
	}

	elapsed := time.Since(start)
	fmt.Printf("done: seen=%d written=%d\n", gamesSeen, gamesWritten)
	fmt.Printf("output: %s\n", outPath)
	fmt.Printf("elapsed: %s\n", elapsed.Round(time.Millisecond))

	return nil
}

func parseGames(reader io.Reader) <-chan GameRecord {
	out := make(chan GameRecord)
	go func() {
		defer close(out)

		scanner := bufio.NewScanner(reader)
		const maxLine = 1024 * 1024
		buf := make([]byte, 0, 64*1024)
		scanner.Buffer(buf, maxLine)

		var rawBuilder strings.Builder
		headers := map[string]string{}
		inGame := false
		moveStarted := false
		gameIndex := 0

		emitGame := func() {
			if !inGame {
				return
			}
			gameIndex++
			raw := rawBuilder.String()
			copiedHeaders := make(map[string]string, len(headers))
			for k, v := range headers {
				copiedHeaders[k] = v
			}
			out <- GameRecord{Raw: raw, Headers: copiedHeaders, Index: gameIndex}
			rawBuilder.Reset()
			headers = map[string]string{}
			inGame = false
			moveStarted = false
		}

		for scanner.Scan() {
			line := scanner.Text()
			lineWithNewline := line + "\n"
			trimmed := strings.TrimSpace(line)

			if strings.HasPrefix(trimmed, "[") {
				if inGame && moveStarted {
					emitGame()
				}
				inGame = true
				rawBuilder.WriteString(lineWithNewline)
				if key, value, ok := parseHeaderLine(trimmed); ok {
					headers[key] = value
				}
				continue
			}

			if inGame {
				rawBuilder.WriteString(lineWithNewline)
				if trimmed != "" {
					moveStarted = true
				}
			}
		}

		if inGame {
			emitGame()
		}
	}()

	return out
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

func matches(game GameRecord, cfg FilterConfig) (bool, []string) {
	reasons := make([]string, 0)
	headers := game.Headers

	if cfg.Variant != "" && headers["Variant"] != cfg.Variant {
		reasons = append(reasons, "variant_mismatch")
	}

	if cfg.TimeControlPrefix != "" {
		tc := headers["TimeControl"]
		if !strings.HasPrefix(tc, cfg.TimeControlPrefix) {
			reasons = append(reasons, "time_control_prefix_mismatch")
		}
	}

	if cfg.MinElo != nil || cfg.MaxElo != nil {
		whiteElo, errWhite := strconv.Atoi(headers["WhiteElo"])
		blackElo, errBlack := strconv.Atoi(headers["BlackElo"])
		if errWhite != nil || errBlack != nil {
			reasons = append(reasons, "elo_parse_fail")
		} else {
			minPlayerElo := minInt(whiteElo, blackElo)
			maxPlayerElo := maxInt(whiteElo, blackElo)

			if cfg.MinElo != nil && minPlayerElo < *cfg.MinElo {
				reasons = append(reasons, "min_elo_fail")
			}
			if cfg.MaxElo != nil && maxPlayerElo > *cfg.MaxElo {
				reasons = append(reasons, "max_elo_fail")
			}
		}
	}

	if cfg.MinSpeed != nil {
		tc := headers["TimeControl"]
		rank, ok := speedRankFromTimeControl(tc)
		if !ok {
			reasons = append(reasons, "min_speed_parse_fail")
		} else if rank < *cfg.MinSpeed {
			reasons = append(reasons, "min_speed_fail")
		}
	}

	if cfg.RatedOnly && !isRatedGame(headers) {
		reasons = append(reasons, "rated_only_fail")
	}

	return len(reasons) == 0, reasons
}

func isRatedGame(headers map[string]string) bool {
	ratedValue := strings.ToLower(strings.TrimSpace(headers["Rated"]))
	if ratedValue != "" {
		return ratedValue == "true" || ratedValue == "1" || ratedValue == "yes"
	}
	event := strings.TrimSpace(headers["Event"])
	return strings.Contains(strings.ToLower(event), "rated")
}

func speedRankFromTimeControl(tc string) (Speed, bool) {
	parts := strings.SplitN(tc, "+", 2)
	if len(parts) != 2 {
		return Bullet, false
	}
	base, errBase := strconv.Atoi(parts[0])
	inc, errInc := strconv.Atoi(parts[1])
	if errBase != nil || errInc != nil {
		return Bullet, false
	}
	estimatedSeconds := base + (40 * inc)
	if estimatedSeconds < 180 {
		return Bullet, true
	}
	if estimatedSeconds < 480 {
		return Blitz, true
	}
	if estimatedSeconds < 1500 {
		return Rapid, true
	}
	return Classical, true
}

func parseSpeed(s string) (Speed, bool) {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "bullet":
		return Bullet, true
	case "blitz":
		return Blitz, true
	case "rapid":
		return Rapid, true
	case "classical":
		return Classical, true
	default:
		return Bullet, false
	}
}

func printTestRun(game GameRecord, match bool, reasons []string) {
	headers := game.Headers
	status := "MATCH"
	if !match {
		status = "NO_MATCH"
	}

	reasonText := "-"
	if len(reasons) > 0 {
		reasonText = strings.Join(reasons, ",")
	}

	fmt.Printf(
		"game=%d whiteElo=%q blackElo=%q timeControl=%q variant=%q rated=%q result=%s reasons=%s\n",
		game.Index,
		headers["WhiteElo"],
		headers["BlackElo"],
		headers["TimeControl"],
		headers["Variant"],
		headers["Rated"],
		status,
		reasonText,
	)
}

func defaultOutputName(inputPath string) string {
	base := filepath.Base(inputPath)
	ext := filepath.Ext(base)
	if ext != "" {
		base = strings.TrimSuffix(base, ext)
	}
	return base + ".filtered.pgn"
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func minEloWasSet() bool {
	return flagWasSet("min-elo")
}

func maxEloWasSet() bool {
	return flagWasSet("max-elo")
}

func flagWasSet(name string) bool {
	set := false
	flag.Visit(func(f *flag.Flag) {
		if f.Name == name {
			set = true
		}
	})
	return set
}
