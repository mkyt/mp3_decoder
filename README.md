# mp3_decoder
yet another MP3 decoder in pure python (work in progress)


done:

- library for binary / bitfield manipulation
- id3 parser
- frame header parser
- sideinfo parser


left to do in decoder pipeline:

- bit reservoir
- huffman decoding
- requantize
- reorder
- stereo process
- alias reduction
- imdct
- freq inversion
- subband synthesis
- wav output


nice to haves:

- reconstruction (export to mp3)
- error / data consistency checking (CRC, flags etc)