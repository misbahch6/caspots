#heuristic dnf(I,J) : before(I,J). [2@2,false]
#heuristic dnf(I,J). [1,false]
#external before(I,J)  : dnf(I,J).

#program skip.
:- dnf(I,J) : (I,J) = @dnf(); not dnf(I,J) : (I,J) = @ndnf().
