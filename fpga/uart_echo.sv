// DE10-Lite UART loopback/echo firmware for first hardware milestone.
// 8N1, 115200 bps; each received byte is retransmitted. No Quartus runtime
// needed on end-user machine once FPGA is configured.
module uart_echo #(
    parameter int CLK_HZ = 50_000_000,
    parameter int BAUD = 115_200,
    parameter int CLKS_PER_BIT = (CLK_HZ + BAUD/2) / BAUD
)(
    input  logic clk,
    input  logic reset_n,
    input  logic uart_rx,
    output logic uart_tx,
    output logic activity
);
    logic rx_meta, rx_sync;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin rx_meta <= 1'b1; rx_sync <= 1'b1; end
        else begin rx_meta <= uart_rx; rx_sync <= rx_meta; end
    end

    typedef enum logic [1:0] {RX_IDLE, RX_START, RX_DATA, RX_STOP} rx_state_t;
    rx_state_t rx_state;
    logic [15:0] rx_timer;
    logic [2:0] rx_bit;
    logic [7:0] rx_data;
    logic rx_valid;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            rx_state <= RX_IDLE; rx_timer <= '0; rx_bit <= '0;
            rx_data <= '0; rx_valid <= 1'b0;
        end else begin
            rx_valid <= 1'b0;
            case (rx_state)
                RX_IDLE: if (!rx_sync) begin
                    rx_timer <= (CLKS_PER_BIT / 2) - 1;
                    rx_state <= RX_START;
                end
                RX_START: if (rx_timer == 0) begin
                    if (!rx_sync) begin rx_timer <= CLKS_PER_BIT - 1; rx_bit <= 0; rx_state <= RX_DATA; end
                    else rx_state <= RX_IDLE;
                end else rx_timer <= rx_timer - 1'b1;
                RX_DATA: if (rx_timer == 0) begin
                    rx_data[rx_bit] <= rx_sync;
                    rx_timer <= CLKS_PER_BIT - 1;
                    if (rx_bit == 7) rx_state <= RX_STOP;
                    else rx_bit <= rx_bit + 1'b1;
                end else rx_timer <= rx_timer - 1'b1;
                RX_STOP: if (rx_timer == 0) begin
                    rx_valid <= rx_sync; // require stop bit HIGH
                    rx_state <= RX_IDLE;
                end else rx_timer <= rx_timer - 1'b1;
                default: rx_state <= RX_IDLE;
            endcase
        end
    end

    typedef enum logic [1:0] {TX_IDLE, TX_START, TX_DATA, TX_STOP} tx_state_t;
    tx_state_t tx_state;
    logic [15:0] tx_timer;
    logic [2:0] tx_bit;
    logic [7:0] tx_data;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            tx_state <= TX_IDLE; tx_timer <= '0; tx_bit <= '0;
            tx_data <= '0; uart_tx <= 1'b1; activity <= 1'b0;
        end else begin
            if (rx_valid) activity <= ~activity;
            case (tx_state)
                TX_IDLE: begin
                    uart_tx <= 1'b1;
                    if (rx_valid) begin
                        tx_data <= rx_data; tx_bit <= 0;
                        tx_timer <= CLKS_PER_BIT - 1;
                        uart_tx <= 1'b0; tx_state <= TX_START;
                    end
                end
                TX_START: if (tx_timer == 0) begin
                    uart_tx <= tx_data[0]; tx_timer <= CLKS_PER_BIT - 1;
                    tx_state <= TX_DATA;
                end else tx_timer <= tx_timer - 1'b1;
                TX_DATA: if (tx_timer == 0) begin
                    tx_timer <= CLKS_PER_BIT - 1;
                    if (tx_bit == 7) begin uart_tx <= 1'b1; tx_state <= TX_STOP; end
                    else begin tx_bit <= tx_bit + 1'b1; uart_tx <= tx_data[tx_bit + 1'b1]; end
                end else tx_timer <= tx_timer - 1'b1;
                TX_STOP: if (tx_timer == 0) tx_state <= TX_IDLE;
                         else tx_timer <= tx_timer - 1'b1;
                default: tx_state <= TX_IDLE;
            endcase
        end
    end
endmodule

module bci_uart_top(
    input  logic MAX10_CLK1_50,
    input  logic [1:0] KEY,
    input  logic UART_RX,
    output logic UART_TX,
    output logic [9:0] LEDR
);
    logic activity;
    uart_echo echo_inst (
        .clk(MAX10_CLK1_50), .reset_n(KEY[0]),
        .uart_rx(UART_RX), .uart_tx(UART_TX), .activity(activity)
    );
    assign LEDR = {9'b0, activity};
endmodule
